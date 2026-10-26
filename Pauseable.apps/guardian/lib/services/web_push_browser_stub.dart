import 'web_push_browser_interface.dart';

WebPushBrowser createWebPushBrowser() => _UnsupportedWebPushBrowser();

class _UnsupportedWebPushBrowser implements WebPushBrowser {
  @override
  bool get isSupported => false;

  @override
  String get permission => 'unsupported';

  @override
  Future<String?> currentSubscription() async => null;

  @override
  Future<String> subscribe(String publicKey) =>
      Future.error(UnsupportedError('Web Push requires a browser.'));

  @override
  Future<bool> unsubscribe() async => false;
}
