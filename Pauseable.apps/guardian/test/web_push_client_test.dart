import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:pauseable_guardian/services/web_push_browser_interface.dart';
import 'package:pauseable_guardian/services/web_push_client.dart';

const _subscription = '''{
  "endpoint":"https://fcm.googleapis.com/fcm/send/test-subscription",
  "keys":{"p256dh":"test-p256dh","auth":"test-auth"}
}''';

class _FakeBrowser implements WebPushBrowser {
  String? subscription;
  bool unsubscribed = false;

  @override
  bool get isSupported => true;

  @override
  String get permission => subscription == null ? 'default' : 'granted';

  @override
  Future<String?> currentSubscription() async => subscription;

  @override
  Future<String> subscribe(String publicKey) async {
    expect(publicKey, 'test-public-key');
    return subscription = _subscription;
  }

  @override
  Future<bool> unsubscribe() async {
    unsubscribed = true;
    subscription = null;
    return true;
  }
}

void main() {
  test('push opt-in, restart sync and opt-out use app Bearer', () async {
    final browser = _FakeBrowser();
    final requests = <http.Request>[];
    final client = WebPushClient(
      baseUrl: 'https://api.example.test',
      patientId: 'byunwoojin',
      appTokenProvider: () => 'test-app-token',
      browser: browser,
      httpClient: MockClient((request) async {
        requests.add(request);
        expect(request.headers['authorization'], 'Bearer test-app-token');
        if (request.method == 'GET') {
          return http.Response(
            jsonEncode({'enabled': true, 'public_key': 'test-public-key'}),
            200,
          );
        }
        return http.Response('', request.method == 'POST' ? 201 : 204);
      }),
    );

    expect((await client.loadState()).subscribed, isFalse);
    await client.enable('test-public-key');
    expect(jsonDecode(requests.last.body)['endpoint'], contains('fcm'));
    expect((await client.loadState()).subscribed, isTrue);
    expect(requests.where((request) => request.method == 'POST'), hasLength(2));
    await client.disable();
    expect(browser.unsubscribed, isTrue);
    expect(requests.last.method, 'DELETE');
    expect(jsonDecode(requests.last.body)['endpoint'], contains('fcm'));
    client.dispose();
  });

  test('failed registration removes the browser subscription', () async {
    final browser = _FakeBrowser();
    final client = WebPushClient(
      baseUrl: 'https://api.example.test',
      patientId: 'byunwoojin',
      appTokenProvider: () => 'test-app-token',
      browser: browser,
      httpClient: MockClient((_) async => http.Response('failure', 503)),
    );
    await expectLater(client.enable('test-public-key'), throwsStateError);
    expect(browser.unsubscribed, isTrue);
    client.dispose();
  });

  test(
    'test targets only current subscription and reports service acceptance',
    () async {
      final browser = _FakeBrowser()..subscription = _subscription;
      final requests = <http.Request>[];
      final client = WebPushClient(
        baseUrl: 'https://api.example.test',
        patientId: 'byunwoojin',
        appTokenProvider: () => 'test-app-token',
        browser: browser,
        httpClient: MockClient((request) async {
          requests.add(request);
          expect(request.headers['authorization'], 'Bearer test-app-token');
          if (request.method == 'POST') {
            expect(jsonDecode(request.body), {
              'endpoint':
                  'https://fcm.googleapis.com/fcm/send/test-subscription',
              'delay_seconds': 10,
            });
            return http.Response(
              '{"test_id":"web-push-test-example","status":"scheduled"}',
              202,
            );
          }
          return http.Response(
            '{"status":"accepted","attempted":1,"accepted":1}',
            200,
          );
        }),
      );
      final testId = await client.scheduleTest();
      expect(await client.testResult(testId), 'accepted');
      expect(requests.map((request) => request.url.path), [
        '/api/patients/byunwoojin/push/test',
        '/api/patients/byunwoojin/push/test/web-push-test-example',
      ]);
      browser.subscription = null;
      await expectLater(client.scheduleTest(), throwsStateError);
      expect(requests.length, 2);
      client.dispose();
    },
  );
}
