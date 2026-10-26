import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:pauseable_guardian/repositories/api_guardian_repository.dart';
import 'package:pauseable_guardian/models/favorite_song.dart';

void main() {
  test(
    'consent uses app auth and validates server receipt before proceeding',
    () async {
      final id = 'a' * 32;
      var mode = 'ok';
      final repository = ApiGuardianRepository(
        baseUrl: 'https://api.example.test',
        patientId: 'byunwoojin',
        appTokenProvider: () => 'consent-session',
        client: MockClient((request) async {
          expect(request.method, 'POST');
          expect(
            request.url.path,
            '/api/patients/byunwoojin/voice-training/consents',
          );
          expect(request.headers['Authorization'], 'Bearer consent-session');
          expect(jsonDecode(request.body), {
            'request_id': id,
            'policy_version': '2026-10-24',
            'accepted': true,
          });
          if (mode == 'offline') return http.Response('{}', 503);
          return http.Response(
            jsonEncode({
              'consent_id': 'voice-consent-$id',
              'policy_version': '2026-10-24',
              'patient_id': mode == 'other' ? 'other-patient' : 'byunwoojin',
              'scope': 'guardian_voice_training',
              'accepted': mode != 'false',
              'accepted_at': '2026-10-24T10:00:00+00:00',
            }),
            201,
          );
        }),
      );
      final receipt = await repository.saveVoiceConsent(requestId: id);
      expect(receipt.consentId, 'voice-consent-$id');
      expect(receipt.acceptedAt.isUtc, isTrue);
      for (final invalid in ['other', 'false']) {
        mode = invalid;
        await expectLater(
          repository.saveVoiceConsent(requestId: id),
          throwsFormatException,
        );
      }
      mode = 'offline';
      await expectLater(
        repository.saveVoiceConsent(requestId: id),
        throwsA(isA<GuardianApiException>()),
      );
    },
  );

  test('preferences keep the legacy contract and add authenticated patient scoping', () async {
    final requests = <http.Request>[];
    final repository = ApiGuardianRepository(
      baseUrl: 'https://api.example.test',
      patientId: 'patient-two',
      appTokenProvider: () => 'prefs-session',
      client: MockClient((request) async {
        requests.add(request);
        return http.Response(
          jsonEncode({'safety_notifications': false, 'sound_enabled': false}),
          200,
        );
      }),
    );
    await repository.loadPreferences();
    final saved = await repository.updatePreferences(
      safetyNotifications: false,
      soundEnabled: false,
    );
    expect(saved.safetyNotifications, isFalse);
    for (final request in requests) {
      expect(request.url.path, '/api/guardians/me/preferences');
      expect(request.url.queryParameters['patient_id'], 'patient-two');
      expect(request.headers['Authorization'], 'Bearer prefs-session');
    }
    expect(jsonDecode(requests.last.body), {
      'safety_notifications': false,
      'sound_enabled': false,
    });
  });

  test(
    'private photos use the configured API and app auth, not a public URL',
    () async {
      final requests = <http.Request>[];
      final repository = ApiGuardianRepository(
        baseUrl: 'https://api.example.test',
        appTokenProvider: () => 'private-app-session',
        client: MockClient((request) async {
          requests.add(request);
          return http.Response.bytes(
            [137, 80, 78, 71],
            200,
            headers: {'content-type': 'image/png'},
          );
        }),
      );
      final bytes = await repository.loadDoorPhoto(eventId: 'camera.001:night');
      expect(bytes, [137, 80, 78, 71]);
      expect(requests.single.url.origin, 'https://api.example.test');
      expect(requests.single.url.pathSegments, [
        'api',
        'door-events',
        'camera.001:night',
        'image',
      ]);
      expect(
        requests.single.headers['Authorization'],
        'Bearer private-app-session',
      );
      expect(requests.single.url.query, isEmpty);
      expect(requests.single.followRedirects, isFalse);
      for (final id in [
        '../secret',
        '.',
        '..',
        'https://other.test/photo',
        'a/b',
      ]) {
        await expectLater(
          repository.loadDoorPhoto(eventId: id),
          throwsArgumentError,
        );
      }
      expect(requests, hasLength(1));
    },
  );

  test(
    'private photo auth failures, redirects and non-images are not displayed',
    () async {
      for (final status in [401, 403, 302, 503, 200]) {
        final repository = ApiGuardianRepository(
          baseUrl: 'https://api.example.test',
          appTokenProvider: () => 'test-session',
          client: MockClient(
            (_) async => http.Response(
              'not a photo',
              status,
              headers: {'content-type': 'text/html'},
            ),
          ),
        );
        await expectLater(
          repository.loadDoorPhoto(eventId: 'camera-001'),
          status == 200
              ? throwsStateError
              : throwsA(isA<GuardianApiException>()),
        );
      }
    },
  );

  test(
    'an old server ignoring the spoken name is not reported as saved',
    () async {
      final repository = ApiGuardianRepository(
        baseUrl: 'https://api.example.test',
        client: MockClient(
          (_) async => http.Response(
            jsonEncode({
              'name': 'guardian',
              'patient_name': 'patient',
              'relationship': 'son',
              'phone_number': '',
            }),
            200,
          ),
        ),
      );
      await expectLater(
        repository.updateGuardianProfile(
          name: 'guardian',
          patientName: 'patient',
          relationship: 'son',
          phoneNumber: '',
          patientCallName: '엄마',
        ),
        throwsStateError,
      );
    },
  );

  test(
    'family TTS address is authenticated and omitted by legacy writes',
    () async {
      final requests = <http.Request>[];
      final repository = ApiGuardianRepository(
        baseUrl: 'https://api.example.test',
        patientId: 'byunwoojin',
        appTokenProvider: () => 'family-app-test',
        client: MockClient((request) async {
          requests.add(request);
          expect(request.headers['authorization'], 'Bearer family-app-test');
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'name': '이보호',
                'patient_name': '박돌봄',
                'relationship': '딸',
                'phone_number': '',
                'patient_call_name': '엄마',
              }),
            ),
            200,
          );
        }),
      );
      final saved = await repository.updateGuardianProfile(
        name: '이보호',
        patientName: '박돌봄',
        relationship: '딸',
        phoneNumber: '',
        patientCallName: '엄마',
      );
      expect(saved.patientCallName, '엄마');
      expect(jsonDecode(requests.last.body)['patient_call_name'], '엄마');
      expect(requests.last.url.path, '/api/patients/byunwoojin/care-profile');
      await repository.updateGuardianProfile(
        name: '이보호',
        patientName: '박돌봄',
        relationship: '딸',
        phoneNumber: '',
      );
      expect(
        jsonDecode(requests.last.body).containsKey('patient_call_name'),
        isFalse,
      );
    },
  );

  test('restores patient alerts and marks one as read through REST', () async {
    final requests = <http.Request>[];
    final repository = ApiGuardianRepository(
      baseUrl: 'https://gateway.example.test',
      patientId: 'byunwoojin',
      client: MockClient((request) async {
        requests.add(request);
        if (request.method == 'GET') {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'patient_id': 'byunwoojin',
                'alerts': [
                  {
                    'alert_id': 'ha-event-001',
                    'occurred_at': '2026-10-04T10:11:12Z',
                    'risk_level': 'caution',
                    'alert_type': 'appliance',
                    'title': '냉장고 문 열림',
                    'message': '상태 변경을 감지했습니다.',
                    'is_read': false,
                  },
                ],
              }),
            ),
            200,
          );
        }
        return http.Response('{"status":"read"}', 200);
      }),
    );

    final alerts = await repository.loadAlertHistory();
    expect(alerts.single.id, 'ha-event-001');
    expect(alerts.single.isRead, isFalse);
    await repository.markAlertRead(alerts.single.id);
    expect(requests.map((request) => request.method), ['GET', 'POST']);
    expect(requests.first.url.path, '/api/patients/byunwoojin/alerts');
    expect(
      requests.last.url.path,
      '/api/patients/byunwoojin/alerts/ha-event-001/read',
    );
  });

  test('favorite songs use patient-scoped REST endpoints', () async {
    final requests = <http.Request>[];
    final repository = ApiGuardianRepository(
      baseUrl: 'https://gateway.example.test',
      patientId: 'byunwoojin',
      client: MockClient((request) async {
        requests.add(request);
        return http.Response(
          jsonEncode({
            'patient_id': 'byunwoojin',
            'songs': [
              {
                'video_id': 'dQw4w9WgXcQ',
                'title': '좋아하는 노래',
                'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
              },
            ],
          }),
          200,
          headers: const {'content-type': 'application/json; charset=utf-8'},
        );
      }),
    );
    final songs = await repository.loadFavoriteSongs();
    await repository.saveFavoriteSongs(songs);
    expect(requests.map((request) => request.method), ['GET', 'PUT']);
    expect(
      requests.map((request) => request.url.path),
      everyElement('/api/patients/byunwoojin/favorite-songs'),
    );
    expect(jsonDecode(requests.last.body), {
      'songs': [
        {
          'title': '좋아하는 노래',
          'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        },
      ],
    });
    expect(songs.single, isA<FavoriteSong>());
  });

  test(
    'explicit Gateway patient ID is used in URLs and WAV multipart fields',
    () async {
      final requests = <http.Request>[];
      final repository = ApiGuardianRepository(
        baseUrl: 'https://gateway.example.test',
        patientId: 'gateway-test-002',
        client: MockClient((request) async {
          requests.add(request);
          return http.Response(
            jsonEncode({
              'target_seconds': 800,
              'recorded_seconds': 0,
              'clip_count': 0,
              'is_ready': false,
            }),
            200,
          );
        }),
      );
      await repository.loadVoiceTrainingProgress();
      await repository.uploadVoiceTrainingClip(
        audioBytes: Uint8List(4),
        fileName: 'S001.wav',
        durationSeconds: 2,
        promptText: '테스트',
      );
      expect(
        requests.first.url.path,
        '/api/patients/gateway-test-002/voice-training',
      );
      expect(
        requests.last.body,
        contains('name="patient_id"\r\n\r\ngateway-test-002'),
      );
      expect(requests.last.body, isNot(contains('patient-001')));
    },
  );

  test(
    'home settings send only canonical region code and parse server grid',
    () async {
      final payload = {
        'region': {
          'code': '1111051500',
          'province': '서울특별시',
          'city': '종로구',
          'district': '청운효자동',
          'nx': 60,
          'ny': 127,
          'latitude': 37.5841367,
          'longitude': 126.9706519,
        },
        'auto_lighting_enabled': true,
        'lighting': {'status': 'awaiting_integration'},
      };
      final methods = <String>[];
      final repository = ApiGuardianRepository(
        baseUrl: 'http://localhost:8002',
        client: MockClient((request) async {
          methods.add(request.method);
          expect(request.url.path, '/api/patients/byunwoojin/home-environment');
          if (request.method == 'PUT') {
            expect(jsonDecode(request.body), {
              'region_code': '1111051500',
              'auto_lighting_enabled': true,
            });
          }
          return http.Response(
            jsonEncode(payload),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );
      final saved = await repository.updateHomeEnvironment(
        regionCode: '1111051500',
        autoLightingEnabled: true,
      );
      expect(saved.region?.nx, 60);
      expect(saved.region?.label, '서울특별시 종로구 청운효자동');
      expect(
        (await repository.loadHomeEnvironment()).statusLabel,
        '자동 조명용 지역 저장됨',
      );
      expect(methods, ['PUT', 'GET']);
    },
  );

  test('loads and converts dashboard data from FastAPI', () async {
    final client = MockClient((request) async {
      expect(request.method, 'GET');
      expect(
        request.url.toString(),
        'http://127.0.0.1:8000/api/patients/byunwoojin/dashboard',
      );
      return http.Response(
        jsonEncode(_snapshotJson),
        200,
        headers: const {'content-type': 'application/json; charset=utf-8'},
      );
    });
    final repository = ApiGuardianRepository(
      baseUrl: 'http://127.0.0.1:8000/',
      client: client,
    );

    final snapshot = await repository.loadSnapshot();

    expect(snapshot.patient.name, '김영희');
    expect(snapshot.repetitiveBehaviorAlert.currentCount, 7);
    expect(snapshot.doorEvents.single.directionLabel, '외출');
  });

  testWidgets('dashboard waits for slow server startup beyond eight seconds', (
    tester,
  ) async {
    var requests = 0;
    final repository = ApiGuardianRepository(
      baseUrl: 'https://gateway.example.test',
      client: MockClient((request) async {
        requests++;
        await Future<void>.delayed(const Duration(seconds: 55));
        return http.Response(
          jsonEncode(_snapshotJson),
          200,
          headers: const {'content-type': 'application/json; charset=utf-8'},
        );
      }),
    );
    var completed = false;
    String? loadedName;
    Object? error;
    final loaded = repository.loadSnapshot().then(
      (snapshot) {
        loadedName = snapshot.patient.name;
        completed = true;
      },
      onError: (Object failure) {
        error = failure;
      },
    );
    await tester.pump();
    await tester.pump(const Duration(seconds: 9));
    expect(error, isNull);
    expect(completed, isFalse);
    await tester.pump(const Duration(seconds: 46));
    await loaded;
    expect(error, isNull);
    expect(completed, isTrue);
    expect(loadedName, '김영희');
    expect(requests, 1);
  });

  testWidgets('dashboard timeout is bounded and never repeats the request', (
    tester,
  ) async {
    var requests = 0;
    final repository = ApiGuardianRepository(
      baseUrl: 'https://gateway.example.test',
      client: MockClient((request) {
        requests++;
        return Completer<http.Response>().future;
      }),
    );
    Object? error;
    final loaded = repository.loadSnapshot().then<void>(
      (_) => fail('An unresponsive server must not return a snapshot'),
      onError: (Object failure) {
        error = failure;
      },
    );
    await tester.pump();
    await tester.pump(const Duration(seconds: 74));
    expect(error, isNull);
    await tester.pump(const Duration(seconds: 1));
    await loaded;
    expect(error, isA<TimeoutException>());
    expect(requests, 1);
  });

  test('sends pause and resume requests to FastAPI', () async {
    final requests = <http.Request>[];
    final client = MockClient((request) async {
      requests.add(request);
      return http.Response('{}', 200);
    });
    final repository = ApiGuardianRepository(
      baseUrl: 'http://127.0.0.1:8000',
      client: client,
    );

    await repository.pauseAlert(
      alertId: 'alert-door-001',
      duration: const Duration(hours: 1),
    );
    await repository.resumeAlert(alertId: 'alert-door-001');
    await repository.confirmDoorEvent(eventId: 'door-event-001');
    await repository.activateDemoScenario(scenarioId: 'inactivity');

    expect(requests[0].method, 'POST');
    expect(requests[0].url.path, '/api/alerts/alert-door-001/pause');
    expect(jsonDecode(requests[0].body), {'duration_minutes': 60});
    expect(requests[1].url.path, '/api/alerts/alert-door-001/resume');
    expect(requests[2].url.path, '/api/door-events/door-event-001/confirm');
    expect(requests[3].url.path, '/api/demo/scenarios/inactivity');
  });

  test('uploads a WAV voice message as multipart data', () async {
    late http.Request capturedRequest;
    final client = MockClient((request) async {
      capturedRequest = request;
      return http.Response('{"status":"uploaded"}', 201);
    });
    final repository = ApiGuardianRepository(
      baseUrl: 'http://127.0.0.1:8000',
      client: client,
    );

    await repository.uploadVoiceMessage(
      audioBytes: _testWaveBytes,
      fileName: 'guardian.wav',
      durationSeconds: 3,
    );

    expect(capturedRequest.method, 'POST');
    expect(capturedRequest.url.path, '/api/voice-messages');
    expect(
      capturedRequest.headers['content-type'],
      startsWith('multipart/form-data'),
    );
    final body = capturedRequest.body;
    expect(body, contains('name="patient_id"'));
    expect(body, contains('byunwoojin'));
    expect(body, contains('name="duration_seconds"'));
    expect(body, contains('name="file"; filename="guardian.wav"'));
  });

  test(
    'supports profile, preferences, device and contact action APIs',
    () async {
      final requests = <http.Request>[];
      final client = MockClient((request) async {
        requests.add(request);
        final path = request.url.path;
        if (path == '/api/patients/byunwoojin/care-profile') {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'name': '김보호',
                'patient_name': '김영희',
                'relationship': '김영희 님의 보호자',
                'phone_number': '010-1234-5678',
              }),
            ),
            200,
            headers: const {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (path == '/api/guardians/me/preferences') {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'safety_notifications': false,
                'sound_enabled': true,
              }),
            ),
            200,
            headers: const {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (path.contains('device-connection')) {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'device_name': 'PAUSEABLE Home',
                'is_online': true,
                'last_checked_label': '방금 전',
                'services': [
                  {
                    'name': 'Home Assistant',
                    'is_connected': true,
                    'detail': '가상 연결',
                  },
                ],
              }),
            ),
            200,
            headers: const {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return http.Response.bytes(
          utf8.encode(
            jsonEncode({
              'title': path.contains('emergency')
                  ? '긴급 연락 요청 완료'
                  : '보호 전화 요청 완료',
              'message': '가상 요청을 보냈습니다.',
              'reference_id': 'demo-001',
            }),
          ),
          200,
          headers: const {'content-type': 'application/json; charset=utf-8'},
        );
      });
      final repository = ApiGuardianRepository(
        baseUrl: 'http://127.0.0.1:8000',
        client: client,
      );

      final profile = await repository.loadGuardianProfile();
      final updatedProfile = await repository.updateGuardianProfile(
        name: '김보호',
        patientName: '김영희',
        relationship: '김영희 님의 보호자',
        phoneNumber: '010-1234-5678',
      );
      final preferences = await repository.loadPreferences();
      final savedPreferences = await repository.updatePreferences(
        safetyNotifications: false,
        soundEnabled: true,
      );
      final device = await repository.loadDeviceConnection();
      await repository.checkDeviceConnection();
      final careCall = await repository.requestCareCall();
      final emergency = await repository.requestEmergencyContact();

      expect(profile.name, '김보호');
      expect(profile.patientName, '김영희');
      final profileWrite = requests.singleWhere(
        (request) =>
            request.method == 'PUT' &&
            request.url.path.endsWith('/care-profile'),
      );
      expect(jsonDecode(profileWrite.body)['patient_name'], '김영희');
      expect(updatedProfile.phoneNumber, '010-1234-5678');
      expect(preferences.soundEnabled, isTrue);
      expect(savedPreferences.safetyNotifications, isFalse);
      expect(device.services.single.name, 'Home Assistant');
      expect(careCall.title, '보호 전화 요청 완료');
      expect(emergency.title, '긴급 연락 요청 완료');
      expect(
        requests.map((request) => request.method),
        containsAll(['GET', 'PUT', 'POST']),
      );
    },
  );

  test(
    'new training session is authenticated and its id is bound to each WAV',
    () async {
      final requests = <http.Request>[];
      final repository = ApiGuardianRepository(
        baseUrl: 'https://api.example.test',
        appTokenProvider: () => 'session-test-token',
        client: MockClient((request) async {
          requests.add(request);
          expect(request.headers['authorization'], 'Bearer session-test-token');
          if (request.url.path.endsWith('/sessions')) {
            expect(request.method, 'POST');
            expect(jsonDecode(request.body), {
              'previous_job_id': 'voice-job-111111111111',
            });
          }
          return http.Response(
            jsonEncode({
              'target_seconds': 800,
              'recorded_seconds': 0,
              'clip_count': 0,
              'is_ready': false,
              'job_id': 'voice-job-222222222222',
              'job_status': 'collecting',
              'total_prompts': 160,
            }),
            201,
          );
        }),
      );
      final progress = await repository.startNewVoiceTraining(
        previousJobId: 'voice-job-111111111111',
      );
      expect(progress.jobId, 'voice-job-222222222222');
      expect(progress.canRecord, isTrue);
      await repository.uploadVoiceTrainingClip(
        audioBytes: _testWaveBytes,
        fileName: 'S001.wav',
        durationSeconds: 3,
        promptText: '새 녹음 문장',
        jobId: progress.jobId,
      );
      expect(requests.last.body, contains('name="job_id"'));
      expect(requests.last.body, contains('voice-job-222222222222'));
    },
  );

  test('loads progress and uploads a voice training clip', () async {
    http.Request? uploadRequest;
    final client = MockClient((request) async {
      if (request.method == 'GET') {
        expect(request.url.path, '/api/patients/byunwoojin/voice-training');
        return http.Response(
          jsonEncode({
            'target_seconds': 800,
            'recorded_seconds': 120,
            'clip_count': 3,
            'is_ready': false,
          }),
          200,
        );
      }
      uploadRequest = request;
      return http.Response(
        jsonEncode({
          'target_seconds': 800,
          'recorded_seconds': 140,
          'clip_count': 4,
          'is_ready': false,
        }),
        201,
      );
    });
    final repository = ApiGuardianRepository(
      baseUrl: 'http://127.0.0.1:8000',
      client: client,
    );

    final before = await repository.loadVoiceTrainingProgress();
    final after = await repository.uploadVoiceTrainingClip(
      audioBytes: _testWaveBytes,
      fileName: 'training.wav',
      durationSeconds: 20,
      promptText: '안심하고 천천히 쉬어 주세요.',
    );

    expect(before.recordedSeconds, 120);
    expect(after.recordedSeconds, 140);
    expect(uploadRequest?.url.path, '/api/voice-training/clips');
    expect(uploadRequest?.body, contains('name="prompt_text"'));
    expect(uploadRequest?.body, contains('안심하고 천천히 쉬어 주세요.'));
  });

  test('throws a typed error when FastAPI returns an error', () async {
    final repository = ApiGuardianRepository(
      baseUrl: 'http://127.0.0.1:8000',
      client: MockClient((_) async => http.Response('server error', 500)),
    );

    expect(
      repository.loadSnapshot(),
      throwsA(
        isA<GuardianApiException>().having(
          (error) => error.statusCode,
          'statusCode',
          500,
        ),
      ),
    );
  });
}

final _testWaveBytes = Uint8List.fromList([
  ...'RIFF'.codeUnits,
  36,
  0,
  0,
  0,
  ...'WAVEfmt '.codeUnits,
  ...List<int>.filled(28, 0),
]);

const _snapshotJson = {
  'demo_scenario': 'repetitive_behavior',
  'patient': {
    'id': 'byunwoojin',
    'name': '김영희',
    'location': '거실',
    'activity': '휴식 중',
    'is_device_connected': true,
    'last_connected_label': '방금 전',
    'safety_label': '안전',
    'day_summary': '특이사항 없음',
  },
  'alerts': [
    {
      'id': 'alert-door-001',
      'type': 'repetitive_behavior',
      'category': '확인 필요',
      'title': '현관문 반복 행동 감지',
      'description': '최근 20분 동안 현관문을 7회 열고 닫았어요.',
      'time_label': '오늘 오후 2:42',
      'device_id': 'front-door',
      'current_count': 7,
      'normal_min': 0,
      'normal_max': 2,
    },
  ],
  'door_events': [
    {
      'id': 'door-event-001',
      'occurred_at': '2026-08-18T16:42:00+09:00',
      'time_label': '오늘 오후 4:42',
      'direction': 'exit',
      'title': '외출 장면 감지',
      'description': '현관문이 열리고 외출하는 장면이 촬영됐어요.',
      'image_url': 'http://127.0.0.1:8000/api/door-events/door-event-001/image',
      'is_confirmed': false,
    },
  ],
  'activity': {
    'events': [
      {
        'occurred_at': '2026-08-26T07:30:12+09:00',
        'time_label': '오전 7:30:12',
        'title': '침실 조명 켜짐',
        'type': 'light',
        'state': 'on',
      },
    ],
  },
};
