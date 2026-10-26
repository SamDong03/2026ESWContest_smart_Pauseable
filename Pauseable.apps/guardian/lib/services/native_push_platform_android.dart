import 'dart:async';
import 'dart:convert';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

import 'native_push_platform_interface.dart';

const _channel = AndroidNotificationChannel(
  'pauseable_guardian_alerts',
  '보호자 안전 알림',
  description: '반복행동·배회 등 보호자의 확인이 필요한 상황',
  importance: Importance.high,
  playSound: true,
);
const _silentChannel = AndroidNotificationChannel(
  'pauseable_guardian_alerts_silent',
  '보호자 안전 알림 (무음)',
  description: '알림음을 끈 상태의 보호자 안전 알림',
  importance: Importance.high,
  playSound: false,
  enableVibration: false,
);


@pragma('vm:entry-point')
Future<void> _onBackgroundMessage(RemoteMessage message) async {
  await Firebase.initializeApp();
}

NativePushPlatform createNativePushPlatform() => _AndroidNativePush();

class _AndroidNativePush implements NativePushPlatform {
  final _local = FlutterLocalNotificationsPlugin();
  final _opens = StreamController<void>.broadcast();
  final _seen = <String>{};
  StreamSubscription<RemoteMessage>? _foreground;
  StreamSubscription<RemoteMessage>? _opened;
  bool _initialized = false;
  bool _initialOpen = false;

  FirebaseMessaging get _messaging => FirebaseMessaging.instance;
  AndroidFlutterLocalNotificationsPlugin? get _android => _local
      .resolvePlatformSpecificImplementation<
        AndroidFlutterLocalNotificationsPlugin
      >();

  @override
  bool get isSupported =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.android;
  @override
  Stream<String> get tokenRefreshes => _messaging.onTokenRefresh;
  @override
  Stream<void> get notificationOpens => _opens.stream;


  bool _isGuardianNotification(Map<String, dynamic> data) =>
      data['type'] == 'guardian_alert' || data['type'] == 'push_test';

  void _handleOpen(Map<String, dynamic> data) {
    if (!_isGuardianNotification(data)) return;
    _initialOpen = true;
    if (!_opens.isClosed) _opens.add(null);
  }

  @override
  Future<void> initialize(String patientId) async {
    if (_initialized) return;
    try {


      await Firebase.initializeApp();
    } catch (_) {
      throw const NativePushSetupException();
    }
    FirebaseMessaging.onBackgroundMessage(_onBackgroundMessage);
    await _local.initialize(
      settings: const InitializationSettings(
        android: AndroidInitializationSettings('ic_stat_notification'),
      ),
      onDidReceiveNotificationResponse: (response) {
        final payload = response.payload;
        if (payload == null) return;
        try {
          _handleOpen(jsonDecode(payload) as Map<String, dynamic>);
        } catch (_) {

        }
      },
    );
    await _android?.createNotificationChannel(_channel);
    await _android?.createNotificationChannel(_silentChannel);
    _foreground = FirebaseMessaging.onMessage.listen((message) {
      unawaited(_showForeground(message));
    });
    _opened = FirebaseMessaging.onMessageOpenedApp.listen(
      (message) => _handleOpen(message.data),
    );
    final initialRemote = await _messaging.getInitialMessage();
    if (initialRemote != null) _handleOpen(initialRemote.data);
    final initialLocal = await _local.getNotificationAppLaunchDetails();
    final payload = initialLocal?.notificationResponse?.payload;
    if (initialLocal?.didNotificationLaunchApp == true && payload != null) {
      try {
        _handleOpen(jsonDecode(payload) as Map<String, dynamic>);
      } catch (_) {

      }
    }
    _initialized = true;
  }

  Future<void> _showForeground(RemoteMessage message) async {
    if (!_isGuardianNotification(message.data) ||
        message.notification == null) {
      return;
    }
    final id = message.data['alert_id']?.toString() ?? message.messageId;
    if (id == null || !_seen.add(id)) return;
    if (_seen.length > 256) _seen.remove(_seen.first);
    final soundEnabled = message.data['sound_enabled'] != '0';
    final channel = soundEnabled ? _channel : _silentChannel;
    try {
      await _local.show(
        id: _notificationId(id),
        title: message.notification!.title,
        body: message.notification!.body,
        notificationDetails: NotificationDetails(
          android: AndroidNotificationDetails(
            channel.id,
            channel.name,
            channelDescription: channel.description,
            importance: Importance.high,
            priority: Priority.high,
            icon: 'ic_stat_notification',
            playSound: soundEnabled,
            enableVibration: soundEnabled,
          ),
        ),
        payload: jsonEncode(message.data),
      );
    } catch (_) {

    }
  }

  int _notificationId(String value) {
    var result = 0;
    for (final unit in value.codeUnits) {
      result = ((result * 31) + unit) & 0x7fffffff;
    }
    return result;
  }

  @override
  Future<NativePushPermission> permission({required bool request}) async {
    final settings = request
        ? await _messaging.requestPermission(alert: true, sound: true)
        : await _messaging.getNotificationSettings();
    if (settings.authorizationStatus == AuthorizationStatus.notDetermined) {
      return NativePushPermission.notDetermined;
    }
    if (settings.authorizationStatus == AuthorizationStatus.denied ||
        await _android?.areNotificationsEnabled() == false) {
      return NativePushPermission.denied;
    }
    final channels = await _android?.getNotificationChannels();
    final blockedChannels = channels
        ?.where(
          (channel) =>
              (channel.id == _channel.id || channel.id == _silentChannel.id) &&
              channel.importance == Importance.none,
        )
        .length;
    if (blockedChannels == 2) {
      return NativePushPermission.denied;
    }
    return NativePushPermission.granted;
  }

  @override
  Future<String?> token() => _messaging.getToken();
  @override
  bool consumeInitialNotificationOpen() {
    final value = _initialOpen;
    _initialOpen = false;
    return value;
  }

  @override
  Future<void> openNotificationSettings() async {
    await _android?.openAppNotificationSettings();
  }

  @override
  Future<void> dispose() async {
    await _foreground?.cancel();
    await _opened?.cancel();
    await _opens.close();
  }
}
