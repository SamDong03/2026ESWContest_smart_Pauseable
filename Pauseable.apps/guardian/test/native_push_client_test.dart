import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:pauseable_guardian/services/native_push_client.dart';
import 'package:pauseable_guardian/services/native_push_platform_interface.dart';

class _FakePlatform implements NativePushPlatform {
  final tokens = StreamController<String>.broadcast();
  final opens = StreamController<void>.broadcast();
  NativePushPermission currentPermission = NativePushPermission.granted;
  String? currentToken = 'first-device-token';
  bool initialOpen = false;
  bool missingConfig = false;
  bool supported = true;
  int permissionRequests = 0;
  int initializations = 0;

  @override
  bool get isSupported => supported;
  @override
  Stream<String> get tokenRefreshes => tokens.stream;
  @override
  Stream<void> get notificationOpens => opens.stream;
  @override
  Future<void> initialize(String patientId) async {
    initializations++;
    if (missingConfig) throw const NativePushSetupException();
  }

  @override
  Future<NativePushPermission> permission({required bool request}) async {
    if (request) permissionRequests++;
    return currentPermission;
  }

  @override
  Future<String?> token() async => currentToken;
  @override
  bool consumeInitialNotificationOpen() {
    final result = initialOpen;
    initialOpen = false;
    return result;
  }

  @override
  Future<void> openNotificationSettings() async {}
  @override
  Future<void> dispose() async {
    await tokens.close();
    await opens.close();
  }
}

NativePushClient _client(
  _FakePlatform platform,
  Future<http.Response> Function(http.Request) handler, {
  String token = 'test-app-token',
}) => NativePushClient(
  baseUrl: 'https://api.example.test',
  patientId: 'byunwoojin',
  appTokenProvider: () => token,
  httpClient: MockClient(handler),
  platform: platform,
);

http.Response _success(http.Request request) => switch (request.method) {
  'GET' => http.Response('{"configured":true}', 200),
  'PUT' => http.Response('{"registered":true}', 201),
  'DELETE' => http.Response('', 204),
  'POST' => http.Response('{"attempted":1,"accepted":1}', 200),
  _ => throw StateError('Unexpected method'),
};

void main() {
  test(
    'registration, resume sync and targeted test use authenticated API',
    () async {
      final platform = _FakePlatform();
      final requests = <http.Request>[];
      final client = _client(platform, (request) async {
        requests.add(request);
        expect(request.headers['authorization'], 'Bearer test-app-token');
        expect(
          request.url.path,
          startsWith('/api/patients/byunwoojin/native-push/'),
        );
        return _success(request);
      });
      await client.refresh(requestPermission: true);
      expect(client.status, NativePushStatus.registered);
      expect(platform.permissionRequests, 1);
      final registration = requests.singleWhere(
        (request) => request.method == 'PUT',
      );
      expect(jsonDecode(registration.body), {
        'token': 'first-device-token',
        'platform': 'android',
      });
      await client.refresh();
      expect(platform.initializations, 1);
      expect(platform.permissionRequests, 1);
      expect(
        requests.where((request) => request.method == 'PUT'),
        hasLength(2),
      );
      final testResult = await client.sendTest();
      expect(testResult.accepted, 1);
      expect(requests.last.url.path, endsWith('/test'));
      expect(jsonDecode(requests.last.body), {
        'token': 'first-device-token',
        'delay_seconds': 10,
      });
      client.dispose();
    },
  );

  test(
    'missing app authentication cannot send API calls or initialize Firebase',
    () async {
      final platform = _FakePlatform();
      final client = _client(
        platform,
        (_) async => fail('Unexpected API call'),
        token: '',
      );
      await client.refresh(requestPermission: true);
      expect(client.status, NativePushStatus.authenticationMissing);
      expect(platform.initializations, 0);
      client.dispose();
    },
  );

  test(
    'missing Firebase config is actionable and does not crash startup',
    () async {
      final platform = _FakePlatform()..missingConfig = true;
      final client = _client(
        platform,
        (_) async => fail('Unexpected API call'),
      );
      await client.refresh();
      expect(client.status, NativePushStatus.firebaseNotConfigured);
      expect(client.busy, isFalse);
      client.dispose();
    },
  );

  test(
    'disabled server does not request phone permission or register a token',
    () async {
      final platform = _FakePlatform();
      final client = _client(platform, (request) async {
        expect(request.method, 'GET');
        return http.Response('{"configured":false}', 200);
      });
      await client.refresh(requestPermission: true);
      expect(client.status, NativePushStatus.serverNotConfigured);
      expect(platform.permissionRequests, 0);
      client.dispose();
    },
  );

  test(
    'denial removes the existing registration and blocks test notifications',
    () async {
      final platform = _FakePlatform();
      final requests = <http.Request>[];
      final client = _client(platform, (request) async {
        requests.add(request);
        return _success(request);
      });
      await client.refresh();
      platform.currentPermission = NativePushPermission.denied;
      await client.refresh();
      expect(client.status, NativePushStatus.permissionDenied);
      expect(requests.last.method, 'DELETE');
      expect(jsonDecode(requests.last.body), {'token': 'first-device-token'});
      expect(client.canSendTest, isFalse);
      await expectLater(client.sendTest(), throwsStateError);
      client.dispose();
    },
  );

  test(
    'a refreshed token replaces the previous registration after successful PUT',
    () async {
      final platform = _FakePlatform();
      final requests = <http.Request>[];
      final completed = Completer<void>();
      final client = _client(platform, (request) async {
        requests.add(request);
        if (request.method == 'DELETE') completed.complete();
        return _success(request);
      });
      await client.refresh();
      platform.tokens.add('replacement-device-token');
      await completed.future;
      await Future<void>.delayed(Duration.zero);
      final replacement = requests[requests.length - 2];
      expect(replacement.method, 'PUT');
      expect(jsonDecode(replacement.body)['token'], 'replacement-device-token');
      expect(requests.last.method, 'DELETE');
      expect(jsonDecode(requests.last.body)['token'], 'first-device-token');
      expect(client.status, NativePushStatus.registered);
      client.dispose();
    },
  );

  test(
    'offline registration retries on resume and never reports false success',
    () async {
      final platform = _FakePlatform();
      var offline = true;
      final client = _client(platform, (request) async {
        if (offline && request.method == 'PUT') {
          throw http.ClientException('offline');
        }
        return _success(request);
      });
      await client.refresh();
      expect(client.status, NativePushStatus.connectionFailed);
      expect(client.canSendTest, isFalse);
      offline = false;
      await client.refresh();
      expect(client.status, NativePushStatus.registered);
      client.dispose();
    },
  );

  test(
    '401 is distinguished from connectivity failure without exposing response',
    () async {
      final platform = _FakePlatform();
      final client = _client(
        platform,
        (_) async => http.Response('private detail', 401),
      );
      await client.refresh();
      expect(client.status, NativePushStatus.authenticationRejected);
      client.dispose();
    },
  );

  test(
    'initial notification open is retained until home can consume it',
    () async {
      final platform = _FakePlatform()..initialOpen = true;
      final client = _client(platform, (request) async => _success(request));
      expect(client.consumeNotificationOpen(), isFalse);
      final refresh = client.refresh();
      expect(client.consumeNotificationOpen(), isFalse);
      await refresh;
      expect(client.consumeNotificationOpen(), isTrue);
      expect(client.consumeNotificationOpen(), isFalse);
      final opened = client.notificationOpens.first;
      platform.opens.add(null);
      await opened;
      expect(client.consumeNotificationOpen(), isTrue);
      client.dispose();
    },
  );

  test(
    'web and unsupported native platforms stay on their existing flow',
    () async {
      final platform = _FakePlatform()..supported = false;
      final client = _client(
        platform,
        (_) async => fail('Unexpected API call'),
      );
      await client.refresh();
      expect(client.status, NativePushStatus.unsupported);
      expect(platform.initializations, 0);
      client.dispose();
    },
  );
}
