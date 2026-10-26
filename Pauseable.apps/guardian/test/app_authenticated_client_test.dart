import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:pauseable_guardian/repositories/api_guardian_repository.dart';
import 'package:pauseable_guardian/services/app_authenticated_client.dart';

void main() {
  test(
    'Bearer covers progress GET, JSON updates and multipart WAV uploads',
    () async {
      var token = 'test-app-session-a';
      final requests = <http.Request>[];
      final repository = ApiGuardianRepository(
        baseUrl: 'https://example.test',
        appTokenProvider: () => token,
        client: MockClient((request) async {
          requests.add(request);
          expect(request.headers['authorization'], 'Bearer $token');
          expect(request.followRedirects, isFalse);
          return http.Response(
            jsonEncode({
              'target_seconds': 800,
              'recorded_seconds': 5,
              'clip_count': 1,
              'is_ready': false,
            }),
            request.method == 'POST' ? 201 : 200,
          );
        }),
      );
      await repository.loadVoiceTrainingProgress();
      token = 'test-app-session-b';
      await repository.pauseAlert(
        alertId: 'a1',
        duration: const Duration(minutes: 10),
      );
      await repository.uploadVoiceTrainingClip(
        audioBytes: Uint8List.fromList([82, 73, 70, 70]),
        fileName: 'S001.wav',
        durationSeconds: 5,
        promptText: '테스트 대본',
      );
      expect(requests[0].headers['authorization'], 'Bearer test-app-session-a');
      expect(requests[1].headers['content-type'], contains('application/json'));
      expect(jsonDecode(requests[1].body), {'duration_minutes': 10});
      expect(
        requests[2].headers['content-type'],
        startsWith('multipart/form-data; boundary='),
      );
      expect(requests[2].body, contains('filename="S001.wav"'));
      expect(requests[2].body, contains('name="patient_id"'));
    },
  );

  test(
    'missing or malformed session token fails without a network request',
    () async {
      for (final token in <String?>[null, '', ' ', 'bad\r\nheader']) {
        final client = AppAuthenticatedClient(
          inner: MockClient((_) async => throw TestFailure('must not send')),
          apiBaseUri: Uri.parse('https://example.test'),
          tokenProvider: () => token,
        );
        await expectLater(
          client.get(Uri.parse('https://example.test/api')),
          throwsStateError,
        );
        client.close();
      }
    },
  );

  test('does not send credentials outside configured HTTPS origin', () async {
    for (final url in [
      'https://elsewhere.test/api',
      'https://example.test:444/api',
      'http://example.test/api',
      'https://someone@example.test/api',
    ]) {
      final client = AppAuthenticatedClient(
        inner: MockClient((_) async => throw TestFailure('must not send')),
        apiBaseUri: Uri.parse('https://example.test'),
        tokenProvider: () => 'test-app-session',
      );
      await expectLater(client.get(Uri.parse(url)), throwsStateError);
      client.close();
    }
  });

  test('configured loopback HTTP is permitted for local development', () async {
    final client = AppAuthenticatedClient(
      inner: MockClient((request) async {
        expect(request.headers['authorization'], 'Bearer test-app-session');
        return http.Response('{}', 200);
      }),
      apiBaseUri: Uri.parse('http://127.0.0.1:8002'),
      tokenProvider: () => 'test-app-session',
    );
    expect(
      (await client.get(Uri.parse('http://127.0.0.1:8002/api'))).statusCode,
      200,
    );
    client.close();
  });

  test(
    '401 and 403 remain authentication failures, not successful uploads',
    () async {
      for (final status in [401, 403]) {
        final repository = ApiGuardianRepository(
          baseUrl: 'https://example.test',
          appTokenProvider: () => 'test-app-session',
          client: MockClient(
            (_) async => http.Response('{"detail":"Unauthorized"}', status),
          ),
        );
        await expectLater(
          repository.uploadVoiceTrainingClip(
            audioBytes: Uint8List(4),
            fileName: 'S001.wav',
            durationSeconds: 2,
            promptText: '테스트',
          ),
          throwsA(
            isA<GuardianApiException>().having(
              (e) => e.statusCode,
              'status',
              status,
            ),
          ),
        );
      }
    },
  );
}
