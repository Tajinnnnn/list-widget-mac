"""(C) Isolated native smoke test. Uses an ephemeral WebKit store and fake tasks."""
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import AppKit
import WebKit
import webview
from PyObjCTools import AppHelper
import state
import window_chrome

# pywebview uses defaultDataStore even in private mode (and clears it).
# Supply a nonpersistent store in THIS PROCESS instead; do not clear or use
# the user's List/WebKit store, backup, sync worker, notifications or tray.
store = WebKit.WKWebsiteDataStore.nonPersistentDataStore()
class EphemeralStore:
    @staticmethod
    def defaultDataStore():
        return store
WebKit.WKWebsiteDataStore = EphemeralStore

fixture = {
    'lists': [{'id':'today','name':'Today','items':[
        {'_id':'one','text':'Finish the sidebar','done':False},
        {'_id':'two','text':'Check glass on the desktop','done':False},
    ]}, {'id':'ideas','name':'Ideas','items':[]}],
    'active':'today', 'settings':{'vibrancy':True,'retention':'never','trashRetention':'never'},
    'trash':[], 'islands':[], 'tombstones':[],
}
source = (Path(__file__).resolve().parents[1] / 'todo.html').read_text()
seed = '<script>window.previewErrors=[]; window.addEventListener("error",e=>window.previewErrors.push(e.message)); localStorage.setItem("todo.widget.v3", '+json.dumps(json.dumps(fixture))+');</script>'
source = source.replace('<script>', seed+'\n<script>',1)

class PreviewApi:
    def set_vibrancy(self, enabled):
        return window_chrome.apply_vibrancy(enabled)
    def save_backup(self, data):
        return True
    def load_backup(self):
        return None

fixture_path = Path(__file__).resolve().parents[1] / 'build/ui-fixtures/native-fixture(C).html'
fixture_path.parent.mkdir(parents=True, exist_ok=True)
fixture_path.write_text(source)
state.window = webview.create_window('List UI Preview (C)', fixture_path.as_uri(), width=520,height=600, min_size=(360,400), js_api=PreviewApi(), background_color='#0a090c')
state.window.events.loaded += window_chrome.configure_window_chrome
failures=[]
def check():
    try:
        for _ in range(80):
            if state.window.evaluate_js('document.body.classList.contains("vibrancy")'):
                break
            time.sleep(.1)
        else:
            print('DIAGNOSTICS',state.window.evaluate_js('JSON.stringify({url:location.href, body:document.body.innerText, ready:typeof Platform, bridge:!!window.pywebview?.api?.set_vibrancy, errors:window.previewErrors})'),flush=True)
            raise AssertionError('startup glass was not acknowledged')
        for enabled in [False, True, False, True]:
            assert window_chrome.apply_vibrancy(enabled), f'native toggle {enabled}'
        # Re-run chrome configuration to exercise the late-startup race.
        window_chrome.configure_window_chrome()
        done=threading.Event()
        def inspect():
            try:
                b=window_chrome._browser_view()
                assert not b.window.isOpaque()
                assert b.window.backgroundColor().alphaComponent()==0
                assert not b.webview.valueForKey_('drawsBackground')
                assert b._vibrancy_view.superview()==b.window.contentView()
                assert b.webview.superview()==b.window.contentView()
                assert not b._vibrancy_view.isHidden()
                assert b._vibrancy_view.frame().size == b.window.contentView().bounds().size
            except Exception as exc:
                failures.append(str(exc))
            finally:
                done.set()
        AppHelper.callAfter(inspect)
        assert done.wait(5)
        assert not failures, failures
        result=state.window.evaluate_js('JSON.stringify({title:document.querySelector("#viewTitle").textContent,glass:document.body.classList.contains("vibrancy"),width:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth})')
        print('NATIVE PASS',result,flush=True)
        if '--hold' in sys.argv:
            return
    except Exception as exc:
        failures.append(str(exc)); print('NATIVE FAIL',repr(exc),flush=True)
    finally:
        if '--hold' not in sys.argv or failures:
            state.window.destroy()
state.window.events.loaded += lambda: threading.Thread(target=check,daemon=True).start()
webview.start(private_mode=False)
if failures:
    raise SystemExit(1)
