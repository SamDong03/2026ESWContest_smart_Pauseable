abstract interface class WebPushBrowser {
  bool get isSupported;
  String get permission;
  Future<String?> currentSubscription();
  Future<String> subscribe(String publicKey);
  Future<bool> unsubscribe();
}
