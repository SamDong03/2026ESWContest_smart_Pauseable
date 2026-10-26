enum NativePushPermission { notDetermined, denied, granted }

class NativePushSetupException implements Exception {
  const NativePushSetupException();
}


abstract interface class NativePushPlatform {
  bool get isSupported;
  Stream<String> get tokenRefreshes;
  Stream<void> get notificationOpens;
  Future<void> initialize(String patientId);
  Future<NativePushPermission> permission({required bool request});
  Future<String?> token();
  bool consumeInitialNotificationOpen();
  Future<void> openNotificationSettings();
  Future<void> dispose();
}
