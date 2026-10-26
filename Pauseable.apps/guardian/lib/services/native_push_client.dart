import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'app_authenticated_client.dart';
import 'native_push_platform.dart';

enum NativePushStatus {
  checking,
  unsupported,
  authenticationMissing,
  authenticationRejected,
  firebaseNotConfigured,
  serverNotConfigured,
  permissionRequired,
  permissionDenied,
  tokenUnavailable,
  connectionFailed,
  registered,
}

class NativePushTestResult {
  const NativePushTestResult({required this.attempted, required this.accepted});
  final int attempted;
  final int accepted;
}

class _NativePushHttpException implements Exception {
  const _NativePushHttpException(this.statusCode);
  final int statusCode;
}


class NativePushClient extends ChangeNotifier {
  NativePushClient({
    required String baseUrl,
    required this.patientId,
    required String? Function() appTokenProvider,
    http.Client? httpClient,
    NativePushPlatform? platform,
  }) : _baseUri = Uri.parse(baseUrl),
       _tokenProvider = appTokenProvider,
       _platform = platform ?? createNativePushPlatform(),
       _client = AppAuthenticatedClient(
         inner: httpClient ?? http.Client(),
         apiBaseUri: Uri.parse(baseUrl),
         tokenProvider: appTokenProvider,
       );

  final Uri _baseUri;
  final String patientId;
  final String? Function() _tokenProvider;
  final NativePushPlatform _platform;
  final http.Client _client;
  final _opens = StreamController<void>.broadcast();
  StreamSubscription<String>? _tokenSubscription;
  StreamSubscription<void>? _openSubscription;
  Future<void>? _refreshInFlight;
  String? _latestToken;
  String? _registeredToken;
  final _obsoleteTokens = <String>{};
  bool _initialized = false;
  bool _pendingOpen = false;
  bool _disposed = false;
  bool _testing = false;
  NativePushStatus _status = NativePushStatus.checking;

  NativePushStatus get status => _status;
  bool get supported => _platform.isSupported;
  bool get busy => _refreshInFlight != null || _testing;
  bool get canSendTest => _status == NativePushStatus.registered && !busy;
  bool get hasPendingNotificationOpen => _pendingOpen;
  Stream<void> get notificationOpens => _opens.stream;

  Uri _uri(String suffix) => _baseUri.resolve(
    '/api/patients/${Uri.encodeComponent(patientId)}/native-push/$suffix',
  );

  void _setStatus(NativePushStatus value) {
    if (_disposed) return;
    _status = value;
    notifyListeners();
  }

  Future<void> refresh({bool requestPermission = false}) async {
    if (_disposed) return;
    final running = _refreshInFlight;
    if (running != null) {
      await running;


      if (requestPermission) await refresh(requestPermission: true);
      return;
    }
    final operation = _refresh(requestPermission: requestPermission);
    _refreshInFlight = operation;
    notifyListeners();
    try {
      await operation;
    } finally {
      _refreshInFlight = null;
      if (!_disposed) notifyListeners();
    }
  }

  Future<void> _refresh({required bool requestPermission}) async {
    if (!_platform.isSupported) {
      _setStatus(NativePushStatus.unsupported);
      return;
    }
    final auth = _tokenProvider()?.trim();
    if (auth == null || auth.isEmpty || RegExp(r'\s').hasMatch(auth)) {
      _setStatus(NativePushStatus.authenticationMissing);
      return;
    }
    _setStatus(NativePushStatus.checking);
    try {
      if (!_initialized) {
        await _platform.initialize(patientId);
        if (_disposed) return;
        _tokenSubscription = _platform.tokenRefreshes.listen((token) {
          _latestToken = token;
          unawaited(_retryRefreshedToken());
        }, onError: (_) => _setStatus(NativePushStatus.tokenUnavailable));
        _openSubscription = _platform.notificationOpens.listen((_) {
          _pendingOpen = true;
          _opens.add(null);
          if (!_disposed) notifyListeners();
        });
        _pendingOpen = _platform.consumeInitialNotificationOpen();
        if (_pendingOpen) {
          _opens.add(null);
          notifyListeners();
        }
        _initialized = true;
      }
      final configResponse = await _client
          .get(_uri('config'))
          .timeout(const Duration(seconds: 60));
      _checkResponse(configResponse, const {200});
      final config = jsonDecode(configResponse.body) as Map<String, dynamic>;
      if (config['configured'] != true) {
        _setStatus(NativePushStatus.serverNotConfigured);
        return;
      }
      final permission = await _platform.permission(request: requestPermission);
      if (permission != NativePushPermission.granted) {


        if (_registeredToken != null) {
          await _unregister(_registeredToken!);
          _registeredToken = null;
        }
        await _retireObsoleteTokens();
        _setStatus(
          permission == NativePushPermission.denied
              ? NativePushStatus.permissionDenied
              : NativePushStatus.permissionRequired,
        );
        return;
      }
      final token = _latestToken ?? await _platform.token();
      if (token == null || token.isEmpty) {
        _setStatus(NativePushStatus.tokenUnavailable);
        return;
      }
      await _register(token);
      final previous = _registeredToken;
      _registeredToken = token;
      if (previous != null && previous != token) {

        _obsoleteTokens.add(previous);
      }
      await _retireObsoleteTokens();
      _setStatus(NativePushStatus.registered);
    } on NativePushSetupException {
      _setStatus(NativePushStatus.firebaseNotConfigured);
    } on _NativePushHttpException catch (error) {
      _setStatus(
        error.statusCode == 401 || error.statusCode == 403
            ? NativePushStatus.authenticationRejected
            : error.statusCode == 404
            ? NativePushStatus.serverNotConfigured
            : NativePushStatus.connectionFailed,
      );
    } catch (_) {
      _setStatus(NativePushStatus.connectionFailed);
    }
  }

  Future<void> _retryRefreshedToken() async {
    await _refreshInFlight;
    await refresh();
  }

  void _checkResponse(http.Response response, Set<int> expected) {
    if (!expected.contains(response.statusCode)) {
      throw _NativePushHttpException(response.statusCode);
    }
  }

  Future<void> _register(String token) async {
    final response = await _client
        .put(
          _uri('registration'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({'token': token, 'platform': 'android'}),
        )
        .timeout(const Duration(seconds: 60));
    _checkResponse(response, const {200, 201});
    if ((jsonDecode(response.body) as Map<String, dynamic>)['registered'] !=
        true) {
      throw const FormatException('Invalid registration response.');
    }
  }

  Future<void> _unregister(String token) async {
    final response = await _client
        .delete(
          _uri('registration'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({'token': token}),
        )
        .timeout(const Duration(seconds: 60));
    _checkResponse(response, const {204});
  }

  Future<void> _retireObsoleteTokens() async {
    for (final token in _obsoleteTokens.toList()) {
      await _unregister(token);
      _obsoleteTokens.remove(token);
    }
  }

  Future<NativePushTestResult> sendTest({int delaySeconds = 10}) async {
    final token = _registeredToken;
    if (!canSendTest || token == null) {
      throw StateError('휴대폰 알림 연결을 먼저 완료해 주세요.');
    }
    if (delaySeconds < 0 || delaySeconds > 15) {
      throw ArgumentError.value(delaySeconds, 'delaySeconds', '0..15');
    }
    _testing = true;
    notifyListeners();
    try {
      final response = await _client
          .post(
            _uri('test'),
            headers: const {'Content-Type': 'application/json'},
            body: jsonEncode({'token': token, 'delay_seconds': delaySeconds}),
          )
          .timeout(const Duration(seconds: 75));
      _checkResponse(response, const {200});
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return NativePushTestResult(
        attempted: data['attempted'] as int,
        accepted: data['accepted'] as int,
      );
    } catch (_) {
      throw StateError('시험 알림을 보내지 못했습니다. 연결 상태를 다시 확인해 주세요.');
    } finally {
      _testing = false;
      if (!_disposed) notifyListeners();
    }
  }

  bool consumeNotificationOpen() {
    final value = _pendingOpen;
    _pendingOpen = false;


    if (_initialized) _platform.consumeInitialNotificationOpen();
    return value;
  }

  Future<void> openNotificationSettings() =>
      _platform.openNotificationSettings();

  @override
  void dispose() {
    _disposed = true;
    unawaited(_tokenSubscription?.cancel() ?? Future<void>.value());
    unawaited(_openSubscription?.cancel() ?? Future<void>.value());
    unawaited(_platform.dispose());
    unawaited(_opens.close());
    _client.close();
    super.dispose();
  }
}
