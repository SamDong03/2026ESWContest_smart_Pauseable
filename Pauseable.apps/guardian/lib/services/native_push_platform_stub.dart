import 'native_push_platform_interface.dart';

NativePushPlatform createNativePushPlatform() => _UnsupportedNativePush();

class _UnsupportedNativePush implements NativePushPlatform {
  @override
  bool get isSupported => false;
  @override
  Stream<String> get tokenRefreshes => const Stream.empty();
  @override
  Stream<void> get notificationOpens => const Stream.empty();
  @override
  Future<void> initialize(String patientId) async {}
  @override
  Future<NativePushPermission> permission({required bool request}) async =>
      NativePushPermission.denied;
  @override
  Future<String?> token() async => null;
  @override
  bool consumeInitialNotificationOpen() => false;
  @override
  Future<void> openNotificationSettings() async {}
  @override
  Future<void> dispose() async {}
}
