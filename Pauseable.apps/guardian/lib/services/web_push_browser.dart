import 'web_push_browser_interface.dart';
import 'web_push_browser_stub.dart'
    if (dart.library.js_interop) 'web_push_browser_web.dart'
    as platform;

WebPushBrowser createWebPushBrowser() => platform.createWebPushBrowser();
