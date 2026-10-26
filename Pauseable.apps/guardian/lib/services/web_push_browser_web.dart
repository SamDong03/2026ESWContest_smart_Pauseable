import 'dart:js_interop';

import 'web_push_browser_interface.dart';

@JS('pauseablePush.isSupported')
external JSBoolean _isSupported();

@JS('pauseablePush.permission')
external JSString _permission();

@JS('pauseablePush.currentSubscription')
external JSPromise<JSString> _currentSubscription();

@JS('pauseablePush.subscribe')
external JSPromise<JSString> _subscribe(JSString publicKey);

@JS('pauseablePush.unsubscribe')
external JSPromise<JSBoolean> _unsubscribe();

WebPushBrowser createWebPushBrowser() => _BrowserWebPush();

class _BrowserWebPush implements WebPushBrowser {
  @override
  bool get isSupported => _isSupported().toDart;

  @override
  String get permission => _permission().toDart;

  @override
  Future<String?> currentSubscription() async {
    final json = (await _currentSubscription().toDart).toDart;
    return json.isEmpty ? null : json;
  }

  @override
  Future<String> subscribe(String publicKey) async =>
      (await _subscribe(publicKey.toJS).toDart).toDart;

  @override
  Future<bool> unsubscribe() async => (await _unsubscribe().toDart).toDart;
}
