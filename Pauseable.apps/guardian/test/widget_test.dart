import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:pauseable_guardian/services/voice_training_script_loader.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:pauseable_guardian/app.dart';
import 'package:pauseable_guardian/services/live_alert_client.dart';
import 'package:pauseable_guardian/models/guardian_snapshot.dart';
import 'package:pauseable_guardian/models/patient_status.dart';
import 'package:pauseable_guardian/models/demo_scenario.dart';
import 'package:pauseable_guardian/models/guardian_alert.dart';
import 'package:pauseable_guardian/models/guardian_support.dart';
import 'package:pauseable_guardian/models/voice_training_progress.dart';
import 'package:pauseable_guardian/models/voice_consent_receipt.dart';
import 'package:pauseable_guardian/models/home_environment.dart';
import 'package:pauseable_guardian/models/favorite_song.dart';
import 'package:pauseable_guardian/models/live_app_alert.dart';
import 'package:pauseable_guardian/models/door_event.dart';
import 'package:pauseable_guardian/screens/favorite_songs_page.dart';
import 'package:pauseable_guardian/screens/home_region_page.dart';
import 'package:pauseable_guardian/services/home_region_catalog.dart';
import 'package:pauseable_guardian/repositories/guardian_repository.dart';
import 'package:pauseable_guardian/repositories/mock_guardian_repository.dart';
import 'package:pauseable_guardian/services/voice_recording_service.dart';
import 'package:pauseable_guardian/services/web_push_browser_interface.dart';
import 'package:pauseable_guardian/services/web_push_client.dart';

void main() {
  late GuardianSnapshot snapshot;
  late Uint8List doorPhotoBytes;

  setUpAll(() async {
    snapshot = await MockGuardianRepository().loadSnapshot();
    doorPhotoBytes = await MockGuardianRepository().loadDoorPhoto(
      eventId: snapshot.doorEvents.first.id,
    );

    await HomeRegionCatalog.load();
    await VoiceTrainingScriptLoader.load();
  });

  testWidgets(
    'consent storage failure blocks microphone and uploads until retry succeeds',
    (tester) async {
      final repository = _MemoryGuardianRepository(snapshot)
        ..failConsentSave = true;
      var recorderCreations = 0;
      await tester.pumpWidget(
        PauseableApp(
          repository: repository,
          voiceRecorderFactory: () {
            recorderCreations++;
            return _FakeVoiceRecorder();
          },
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('이어서 녹음'));
      await tester.pumpAndSettle();
      await _acceptVoiceConsent(tester);
      expect(find.textContaining('동의 기록을 서버에 저장하지 못했어요'), findsOneWidget);
      expect(repository.consentSaveCount, 1);
      expect(recorderCreations, 0);
      expect(repository.voiceUploadAttempts, 0);
      expect(find.text('이 문장 녹음 시작'), findsNothing);
      repository.failConsentSave = false;
      final next = find.byKey(const ValueKey('voice-consent-continue'));
      await tester.ensureVisible(next);
      await tester.tap(next);
      await tester.pumpAndSettle();
      expect(repository.consentSaveCount, 2);
      expect(repository.consentRequestIds.toSet().length, 1);
      expect(recorderCreations, 0);
      await tester.ensureVisible(find.text('이 문장 녹음 시작'));
      await tester.tap(find.text('이 문장 녹음 시작'));
      await tester.pump();
      expect(recorderCreations, 1);
      expect(repository.voiceUploadAttempts, 0);
    },
  );

  testWidgets(
    'first launch selects home, retries failed save and remembers it',
    (tester) async {
      tester.view.physicalSize = const Size(800, 1400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final repository = _MemoryGuardianRepository(snapshot)
        ..homeEnvironment = const HomeEnvironment();
      await tester.pumpWidget(PauseableApp(repository: repository));
      await tester.pumpAndSettle();
      expect(find.text('거주 지역 설정'), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, '지역 저장하고 계속'),
            )
            .onPressed,
        isNull,
      );
      await tester.tap(find.byType(DropdownButtonFormField<String>).at(0));
      await tester.pumpAndSettle();
      await tester.tap(find.text('서울특별시').last);
      await tester.pumpAndSettle();
      await tester.tap(find.byType(DropdownButtonFormField<String>).at(1));
      await tester.pumpAndSettle();
      await tester.tap(find.text('종로구').last);
      await tester.pumpAndSettle();
      await tester.tap(find.byType(DropdownButtonFormField<String>).at(2));
      await tester.pumpAndSettle();
      await tester.tap(find.text('청운효자동').last);
      await tester.pumpAndSettle();
      expect(find.text('자동 조명 밝기 조절'), findsNothing);
      repository.failHomeSave = true;
      await tester.ensureVisible(find.text('지역 저장하고 계속'));
      await tester.tap(find.text('지역 저장하고 계속'));
      await tester.pumpAndSettle();
      expect(repository.homeEnvironment.region, isNull);
      expect(find.textContaining('지역을 저장하지 못했습니다.'), findsOneWidget);
      repository.failHomeSave = false;
      await tester.ensureVisible(find.text('지역 저장하고 계속'));
      await tester.tap(find.text('지역 저장하고 계속'));
      await tester.pumpAndSettle();
      expect(find.text('PAUSEABLE'), findsOneWidget);
      expect(repository.homeEnvironment.region?.code, '1111051500');
      expect(repository.homeEnvironment.autoLightingEnabled, isFalse);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pumpWidget(PauseableApp(repository: repository));
      await tester.pumpAndSettle();
      expect(find.text('거주 지역 설정'), findsNothing);
      expect(find.text('PAUSEABLE'), findsOneWidget);
    },
  );

  testWidgets('skipped home setup can be opened from settings', (tester) async {
    tester.view.physicalSize = const Size(800, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final repository = _MemoryGuardianRepository(snapshot)
      ..homeEnvironment = const HomeEnvironment();
    await tester.pumpWidget(PauseableApp(repository: repository));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('나중에 설정하고 홈으로'));
    await tester.tap(find.text('나중에 설정하고 홈으로'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('설정'));
    await tester.pumpAndSettle();
    expect(find.text('자동 조명용 거주 지역'), findsOneWidget);
    expect(find.text('거주 지역과 날씨'), findsNothing);
    expect(find.text('날씨 연결 준비 중'), findsNothing);
    await tester.scrollUntilVisible(
      find.text('거주 지역 설정 필요'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('거주 지역 설정 필요'));
    await tester.pumpAndSettle();
    expect(find.text('거주 지역 설정'), findsOneWidget);
    expect(find.textContaining('자동 조명에 사용할 날씨 지역'), findsOneWidget);
    expect(
      find.textContaining('지역 저장은 조명 전원이나 밝기를 즉시 바꾸는 명령이 아닙니다'),
      findsOneWidget,
    );
  });

  testWidgets('editing the region preserves the existing lighting preference', (
    tester,
  ) async {
    final repository = _MemoryGuardianRepository(snapshot);
    HomeEnvironment? saved;
    await tester.pumpWidget(
      MaterialApp(
        home: HomeRegionPage(
          repository: repository,
          initial: HomeEnvironment(
            region: repository.homeEnvironment.region,
            autoLightingEnabled: true,
          ),
          onSaved: (value) => saved = value,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('지역 저장하고 계속'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('지역 저장하고 계속'));
    await tester.pumpAndSettle();
    expect(saved, isNotNull);
    expect(saved?.region?.code, repository.homeEnvironment.region?.code);
    expect(saved?.autoLightingEnabled, isTrue);
    expect(repository.homeEnvironment.autoLightingEnabled, isTrue);
  });

  testWidgets('failed automatic sentence upload preserves audio for retry', (
    tester,
  ) async {
    final repository = _MemoryGuardianRepository(snapshot)
      ..failVoiceUpload = true;
    await tester.pumpWidget(
      PauseableApp(
        repository: repository,
        voiceRecorderFactory: _FakeVoiceRecorder.new,
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('이어서 녹음'));
    await tester.pumpAndSettle();
    await _acceptVoiceConsent(tester);
    await tester.ensureVisible(find.text('이 문장 녹음 시작'));
    await tester.tap(find.text('이 문장 녹음 시작'));
    await tester.pump();
    await tester.ensureVisible(find.text('이 문장 녹음 완료 · 자동 전송'));
    await tester.tap(find.text('이 문장 녹음 완료 · 자동 전송'));
    await tester.pumpAndSettle();
    expect(repository.voiceUploadCount, 0);
    expect(find.text('문장 3 / 160'), findsOneWidget);
    expect(find.textContaining('자동 전송에 실패했습니다.'), findsOneWidget);
    repository.failVoiceUpload = false;
    await tester.ensureVisible(find.text('이 문장 다시 전송'));
    await tester.tap(find.text('이 문장 다시 전송'));
    await tester.pumpAndSettle();
    expect(repository.voiceUploadCount, 1);
    expect(repository.lastVoiceFileName, 'S003.wav');
    expect(find.text('문장 4 / 160'), findsOneWidget);
    expect(find.text('이 문장 다시 전송'), findsNothing);
  });

  testWidgets(
    'voice consent refusal leaves live alerts and private photos usable',
    (tester) async {
      final original = snapshot.doorEvents.first;
      final privateScene = DoorEvent(
        id: original.id,
        occurredAt: original.occurredAt,
        timeLabel: original.timeLabel,
        direction: original.direction,
        title: original.title,
        description: original.description,
        imageUrl: 'https://api.example.test/api/door-events/private/image',
        isConfirmed: false,
      );
      final repository = _MemoryGuardianRepository(
        GuardianSnapshot(
          patient: snapshot.patient,
          alerts: snapshot.alerts,
          activity: snapshot.activity,
          doorEvents: [privateScene],
          demoScenario: snapshot.demoScenario,
        ),
      )..photoBytes = doorPhotoBytes;
      final live = _PreferenceLiveClient();
      var recorderCreations = 0;
      await tester.pumpWidget(
        PauseableApp(
          repository: repository,
          liveAlertClient: live,
          voiceRecorderFactory: () {
            recorderCreations++;
            return _FakeVoiceRecorder();
          },
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('보호자 음성 수집·이용 동의'), findsNothing);
      await tester.tap(find.text('이어서 녹음'));
      await tester.pumpAndSettle();
      expect(find.text('보호자 음성 수집·이용 동의'), findsOneWidget);
      expect(find.text('이 문장 녹음 시작'), findsNothing);
      expect(recorderCreations, 0);
      expect(repository.voiceUploadAttempts, 0);
      final next = find.byKey(const ValueKey('voice-consent-continue'));
      expect(tester.widget<FilledButton>(next).onPressed, isNull);
      await tester.ensureVisible(
        find.byKey(const ValueKey('voice-consent-decline')),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('voice-consent-decline')));
      await tester.pumpAndSettle();
      final event = LiveAppAlert.fromJson({
        'alert_id': 'consent-refusal-alert',
        'patient_id': snapshot.patient.id,
        'risk_level': 'caution',
        'alert_type': 'wandering',
        'title': '미동의 후 배회 알림',
        'message': '기존 안전 알림은 계속 전달됩니다.',
        'occurred_at': '2026-10-24T11:22:33Z',
      });
      repository.alertHistory = [event];
      live.controller.add(event);
      await tester.pumpAndSettle();
      await tester.tap(find.text('알림').last);
      await tester.pumpAndSettle();
      expect(find.text('미동의 후 배회 알림'), findsWidgets);
      await tester.tap(find.text('기록'));
      await tester.pumpAndSettle();
      expect(repository.photoLoadCount, greaterThan(0));
      await tester.tap(find.text(snapshot.doorEvents.first.title).last);
      await tester.pumpAndSettle();
      expect(find.text('사진 크게 보기 · 확대'), findsOneWidget);
      await tester.tap(find.text('사진 크게 보기 · 확대'));
      await tester.pumpAndSettle();
      expect(find.byType(InteractiveViewer), findsOneWidget);
      expect(recorderCreations, 0);
      expect(repository.voiceUploadAttempts, 0);
      expect(repository.preferences.safetyNotifications, isTrue);
    },
  );

  testWidgets('voice consent is explicit and never reused after closing', (
    tester,
  ) async {
    final repository = _MemoryGuardianRepository(snapshot);
    var recorderCreations = 0;
    await tester.pumpWidget(
      PauseableApp(
        repository: repository,
        voiceRecorderFactory: () {
          recorderCreations++;
          return _FakeVoiceRecorder();
        },
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('이어서 녹음'));
    await tester.pumpAndSettle();
    final checkbox = find.byKey(const ValueKey('voice-consent-checkbox'));
    expect(tester.widget<CheckboxListTile>(checkbox).value, isFalse);
    await _acceptVoiceConsent(tester);
    expect(recorderCreations, 0);
    await tester.ensureVisible(find.text('녹음 화면 닫기'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('녹음 화면 닫기'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('이어서 녹음'));
    await tester.pumpAndSettle();
    expect(tester.widget<CheckboxListTile>(checkbox).value, isFalse);
    expect(
      tester
          .widget<FilledButton>(
            find.byKey(const ValueKey('voice-consent-continue')),
          )
          .onPressed,
      isNull,
    );
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.text('보호자 음성 수집·이용 동의'), findsNothing);
    expect(recorderCreations, 0);
    expect(repository.voiceUploadAttempts, 0);
  });

  testWidgets('guardian home shows essential care information', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      PauseableApp(repository: _MemoryGuardianRepository(snapshot)),
    );
    await tester.pumpAndSettle();

    expect(find.text('PAUSEABLE'), findsOneWidget);
    expect(find.text('김영희님'), findsOneWidget);
    expect(find.byKey(const ValueKey('care-patient-identity')), findsOneWidget);
    expect(find.text('안전'), findsNothing);
    expect(find.text('활동 상태'), findsNothing);
    expect(find.text('마지막 연결'), findsNothing);
    expect(find.text('오늘 상태'), findsNothing);
    expect(find.text('현재 위치'), findsNothing);
    expect(find.text('3분 전 이동'), findsNothing);

    await tester.scrollUntilVisible(
      find.text('최근 알림'),
      400,
      scrollable: find.byType(Scrollable).first,
    );

    expect(find.text('최근 알림'), findsOneWidget);
    expect(find.text('저녁 복약 시간 예정'), findsNothing);

    await tester.scrollUntilVisible(
      find.text('긴급 연락'),
      400,
      scrollable: find.byType(Scrollable).first,
    );

    expect(find.text('긴급 연락'), findsOneWidget);
    expect(find.text('위치 확인'), findsNothing);
  });

  for (final scenario in [
    DemoScenario.normal,
    DemoScenario.repetitiveBehavior,
  ]) {
    testWidgets(
      'home never renders unverified patient measurements ($scenario)',
      (tester) async {
        final repository = _MemoryGuardianRepository(
          GuardianSnapshot(
            patient: PatientStatus(
              id: snapshot.patient.id,
              name: snapshot.patient.name,
              location: 'UNVERIFIED_LOCATION',
              activity: 'UNVERIFIED_ACTIVITY',
              isDeviceConnected: true,
              lastConnectedLabel: 'UNVERIFIED_CONNECTION',
              safetyLabel: 'UNVERIFIED_SAFETY',
              daySummary: 'UNVERIFIED_SUMMARY',
            ),
            alerts: snapshot.alerts,
            activity: snapshot.activity,
            doorEvents: snapshot.doorEvents,
            demoScenario: scenario,
            repetitiveAlertPauseAvailable: true,
          ),
        );
        await tester.pumpWidget(PauseableApp(repository: repository));
        await tester.pumpAndSettle();
        expect(find.text('김영희님'), findsOneWidget);
        expect(find.textContaining('UNVERIFIED_'), findsNothing);
        for (final label in [
          '현재 위치',
          '활동 상태',
          '마지막 연결',
          '오늘 상태',
          '기기가 정상적으로 연결되어 있어요',
          '현재 정상 상태',
          '데모 상황 실행 중',
          '움직임 정상',
        ]) {
          expect(find.text(label), findsNothing);
        }
        final refresh = find.byTooltip('알림·출입 기록 새로고침');
        await tester.ensureVisible(refresh);
        await tester.pumpAndSettle();
        await tester.tap(refresh);
        await tester.pumpAndSettle();
        expect(find.text('알림과 출입 기록을 새로고침했습니다.'), findsOneWidget);
        expect(find.textContaining('UNVERIFIED_'), findsNothing);
        expect(repository.snapshot.doorEvents, snapshot.doorEvents);
        expect(repository.snapshot.alerts, snapshot.alerts);
      },
    );
  }

  testWidgets(
    'home keeps verified alert-server connection and live notifications',
    (tester) async {
      final live = _ConnectedHomeLiveClient();
      await tester.pumpWidget(
        PauseableApp(
          repository: _MemoryGuardianRepository(snapshot),
          liveAlertClient: live,
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('실시간 알림 서버 연결됨'), findsOneWidget);
      expect(find.text('앱과 알림 서버의 연결 상태이며, 환자·센서의 상태와는 별개예요.'), findsOneWidget);
      expect(find.text('기기가 정상적으로 연결되어 있어요'), findsNothing);
      live.controller.add(
        LiveAppAlert(
          id: 'verified-home-wandering',
          occurredAt: DateTime.now().toUtc(),
          riskLevel: 'caution',
          alertType: 'wandering',
          title: '실제 수신 알림 보존',
          message: '화면 정리 후에도 알림은 수신됩니다.',
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(
        find.widgetWithIcon(IconButton, Icons.notifications_none_rounded),
      );
      await tester.pumpAndSettle();
      expect(find.text('실제 수신 알림 보존'), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  testWidgets('bottom navigation changes guardian tabs', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      PauseableApp(repository: _MemoryGuardianRepository(snapshot)),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('알림'));
    await tester.pumpAndSettle();
    expect(find.text('알림 센터'), findsOneWidget);

    await tester.tap(find.text('기록'));
    await tester.pumpAndSettle();
    expect(find.text('생활 이벤트 기록'), findsOneWidget);
    expect(find.text('감지된 걸음'), findsNothing);
    expect(find.text('수면 시간'), findsNothing);
    expect(find.text('실내 이동'), findsNothing);
    expect(find.text('오늘의 센서 이벤트'), findsOneWidget);
    expect(find.text('냉장고 문 열림'), findsOneWidget);
    expect(find.text('냉장고 문 닫힘'), findsOneWidget);
    expect(find.text('오전 8:10:04'), findsOneWidget);
    expect(find.text('오전 8:10:19'), findsOneWidget);
    expect(find.text('현관문 열림'), findsOneWidget);
    expect(find.text('현관문 닫힘'), findsOneWidget);
    expect(find.text('오후 2:42:08'), findsOneWidget);
    expect(find.text('오후 2:42:17'), findsOneWidget);

    await tester.tap(find.text('설정'));
    await tester.pumpAndSettle();
    expect(find.text('앱 설정'), findsOneWidget);
    expect(find.text('라이트 모드'), findsOneWidget);
    expect(find.text('다크 모드'), findsOneWidget);

    await tester.tap(find.text('다크 모드'));
    await tester.pumpAndSettle();
    expect(
      tester.widget<MaterialApp>(find.byType(MaterialApp)).themeMode,
      ThemeMode.dark,
    );

    await tester.tap(find.text('홈'));
    await tester.pumpAndSettle();
    expect(find.text('오늘도 편안하게 지켜볼게요'), findsOneWidget);
  });

  testWidgets('settings button opts the guardian browser into web push', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(800, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final browser = _TestPushBrowser();
    final pushClient = WebPushClient(
      baseUrl: 'https://api.example.test',
      patientId: 'byunwoojin',
      appTokenProvider: () => 'test-app-token',
      browser: browser,
      httpClient: MockClient((request) async {
        if (request.url.path.endsWith('/push/test')) {
          expect(jsonDecode(request.body)['delay_seconds'], 10);
          return http.Response(
            '{"test_id":"web-push-test-example","status":"scheduled"}',
            202,
          );
        }
        if (request.method == 'GET') {
          return http.Response(
            '{"enabled":true,"public_key":"test-public-key"}',
            200,
          );
        }
        return http.Response('', 201);
      }),
    );
    await tester.pumpWidget(
      PauseableApp(
        repository: _MemoryGuardianRepository(snapshot),
        webPushClient: pushClient,
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('설정'));
    await tester.pumpAndSettle();
    final enablePush = find.widgetWithText(TextButton, '켜기');
    await tester.scrollUntilVisible(
      enablePush,
      300,
      scrollable: find
          .ancestor(of: find.text('앱 설정'), matching: find.byType(Scrollable))
          .first,
    );
    await tester.pumpAndSettle();
    await tester.tap(enablePush);
    await tester.pumpAndSettle();
    expect(browser.subscribed, isTrue);
    expect(find.text('앱을 닫아도 이 브라우저에 알림을 보냅니다.'), findsOneWidget);
    await tester.ensureVisible(find.text('10초 후 시험 알림'));
    await tester.tap(find.text('10초 후 시험 알림'));
    await tester.pumpAndSettle();
    expect(find.textContaining('시험 알림을 예약했어요.'), findsOneWidget);
    expect(find.text('전송 결과 확인'), findsOneWidget);
  });

  testWidgets('restored alert is unread until its detail is opened', (
    tester,
  ) async {
    final repository = _MemoryGuardianRepository(snapshot)
      ..alertHistory = [
        LiveAppAlert(
          id: 'ha-missed-001',
          occurredAt: DateTime.utc(2026, 10, 4, 10, 11, 12),
          riskLevel: 'caution',
          alertType: 'appliance',
          title: '놓친 냉장고 알림',
          message: '문이 열렸습니다.',
        ),
      ];
    await tester.pumpWidget(PauseableApp(repository: repository));
    await tester.pumpAndSettle();
    await tester.tap(find.text('알림'));
    await tester.pumpAndSettle();
    expect(find.textContaining('미확인 1건'), findsOneWidget);
    expect(find.text('놓친 냉장고 알림'), findsOneWidget);

    await tester.tap(find.text('놓친 냉장고 알림'));
    await tester.pumpAndSettle();
    expect(repository.markedReadIds, ['ha-missed-001']);
    expect(find.textContaining('미확인 0건'), findsOneWidget);
  });

  testWidgets(
    'live repeated-behavior alert offers a real notification pause without fake counts',
    (tester) async {
      final repository = _MemoryGuardianRepository(snapshot)
        ..alertHistory = [
          LiveAppAlert(
            id: 'evt-repeated-fridge-001',
            occurredAt: DateTime.utc(2026, 10, 4, 10, 11, 12),
            riskLevel: 'caution',
            alertType: 'repetitive_behavior',
            title: 'AI 반복 행동 감지',
            message: '냉장고 문을 반복해서 확인하는 행동이 감지되었습니다.',
          ),
        ];
      await tester.pumpWidget(PauseableApp(repository: repository));
      await tester.pumpAndSettle();
      final behaviorCard = find.byKey(const ValueKey('home-behavior-alert'));
      await tester.scrollUntilVisible(
        behaviorCard,
        400,
        scrollable: find.byType(Scrollable).first,
      );
      expect(
        find.descendant(of: behaviorCard, matching: find.text('반복행동 감지')),
        findsOneWidget,
      );
      expect(
        find.descendant(of: behaviorCard, matching: find.text('평소 범위')),
        findsNothing,
      );
      expect(
        find.descendant(of: behaviorCard, matching: find.text('최근 20분')),
        findsNothing,
      );
      expect(
        find.descendant(
          of: behaviorCard,
          matching: find.textContaining('null'),
        ),
        findsNothing,
      );
      expect(
        find.descendant(
          of: behaviorCard,
          matching: find.text(
            '감지 시각 · ${repository.alertHistory.single.toGuardianAlert().timeLabel}',
          ),
        ),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: behaviorCard,
          matching: find.text('냉장고 문을 반복해서 확인하는 행동이 감지되었습니다.'),
        ),
        findsOneWidget,
      );
      await tester.tap(find.text('알림'));
      await tester.pumpAndSettle();

      final liveCard = find.ancestor(
        of: find.text('AI 반복 행동 감지'),
        matching: find.byType(Card),
      );
      expect(liveCard, findsOneWidget);
      expect(
        find.descendant(of: liveCard, matching: find.text('정상으로 확인')),
        findsOneWidget,
      );
      await tester.tap(find.text('AI 반복 행동 감지'));
      await tester.pumpAndSettle();
      expect(find.text('정상 상황으로 확인'), findsOneWidget);
      expect(repository.markedReadIds, ['evt-repeated-fridge-001']);
      expect(find.textContaining('null'), findsNothing);
      expect(find.text('감지 횟수'), findsNothing);
    },
  );

  for (final metrics in <({int? count, int? min, int? max})>[
    (count: null, min: 1, max: 3),
    (count: 0, min: null, max: null),
    (count: 7, min: 1, max: null),
    (count: 7, min: null, max: 3),
    (count: 7, min: 1, max: 3),
  ]) {
    testWidgets('behavior metrics guard missing fields: $metrics', (
      tester,
    ) async {
      final alert = GuardianAlert(
        id: 'metric-test',
        type: GuardianAlertType.repetitiveBehavior,
        category: '확인 필요',
        title: '횟수 표시 시험',
        description: '반복 행동을 감지했습니다.',
        timeLabel: '10월 23일 10:11:12',
        currentCount: metrics.count,
        normalMin: metrics.min,
        normalMax: metrics.max,
      );
      final repository = _MemoryGuardianRepository(
        GuardianSnapshot(
          patient: snapshot.patient,
          alerts: [
            alert,
            ...snapshot.alerts.where((item) => !item.isRepetitiveBehavior),
          ],
          activity: snapshot.activity,
          doorEvents: snapshot.doorEvents,
          demoScenario: snapshot.demoScenario,
        ),
      );
      await tester.pumpWidget(PauseableApp(repository: repository));
      await tester.pumpAndSettle();
      final card = find.byKey(const ValueKey('home-behavior-alert'));
      await tester.scrollUntilVisible(
        card,
        400,
        scrollable: find.byType(Scrollable).first,
      );
      expect(
        find.descendant(of: card, matching: find.textContaining('null')),
        findsNothing,
      );
      expect(
        find.descendant(
          of: card,
          matching: find.text('감지 시각 · ${alert.timeLabel}'),
        ),
        findsOneWidget,
      );
      final hasRange =
          metrics.count != null && metrics.min != null && metrics.max != null;
      expect(
        find.descendant(of: card, matching: find.text('평소 범위')),
        hasRange ? findsOneWidget : findsNothing,
      );
      if (metrics.count != null) {
        expect(
          find.descendant(of: card, matching: find.text('${metrics.count}회')),
          findsOneWidget,
        );
      } else {
        expect(
          find.descendant(of: card, matching: find.text('최근 20분')),
          findsNothing,
        );
      }
      final detail = find.descendant(of: card, matching: find.text('상세 보기'));
      await tester.ensureVisible(detail);
      await tester.drag(find.byType(Scrollable).first, const Offset(0, -120));
      await tester.pumpAndSettle();
      await tester.tap(detail);
      await tester.pumpAndSettle();
      expect(find.textContaining('null'), findsNothing);
      expect(
        find.text('감지 횟수'),
        metrics.count == null ? findsNothing : findsOneWidget,
      );
      expect(find.text('감지 시각'), findsOneWidget);
      if (metrics.count != null && !hasRange) {
        expect(find.text('${metrics.count}회'), findsWidgets);
        expect(find.textContaining('평소 '), findsNothing);
      }
    });
  }

  for (final initiallyFails in [false, true]) {
    testWidgets(
      'private photo loads, retries and remains visible in zoom ($initiallyFails)',
      (tester) async {
        final original = snapshot.doorEvents.first;
        final remote = DoorEvent(
          id: original.id,
          occurredAt: original.occurredAt,
          timeLabel: original.timeLabel,
          direction: original.direction,
          title: original.title,
          description: original.description,
          imageUrl: 'https://not-the-api.example/private.jpg',
          isConfirmed: false,
        );
        final repository =
            _MemoryGuardianRepository(
                GuardianSnapshot(
                  patient: snapshot.patient,
                  alerts: snapshot.alerts,
                  activity: snapshot.activity,
                  doorEvents: [remote],
                  demoScenario: snapshot.demoScenario,
                ),
              )
              ..photoBytes = doorPhotoBytes
              ..failPhotoLoad = initiallyFails;
        await tester.pumpWidget(PauseableApp(repository: repository));
        await tester.pumpAndSettle();
        await tester.tap(find.text('기록'));
        await tester.pumpAndSettle();
        expect(repository.photoLoadCount, 1);
        if (initiallyFails) {
          expect(find.text('사진 재시도'), findsWidgets);
          repository.failPhotoLoad = false;
          await tester.tap(find.text('사진 재시도').last);
          await tester.pumpAndSettle();
          expect(repository.photoLoadCount, 2);
        }
        await tester.tap(find.text(original.title).last);
        await tester.pumpAndSettle();
        expect(find.text('사진 크게 보기 · 확대'), findsOneWidget);
        await tester.tap(find.text('사진 크게 보기 · 확대'));
        await tester.pumpAndSettle();
        expect(find.byType(InteractiveViewer), findsOneWidget);
        expect(
          find.byWidgetPredicate(
            (widget) => widget is Image && widget.image is MemoryImage,
          ),
          findsWidgets,
        );
        expect(repository.photoLoadCount, initiallyFails ? 2 : 1);
        expect(tester.takeException(), isNull);
      },
    );
  }

  testWidgets(
    'failed settings load disables changes until retry and failed save rolls back',
    (tester) async {
      final repository = _MemoryGuardianRepository(snapshot)
        ..failPreferencesLoad = true;
      await tester.pumpWidget(PauseableApp(repository: repository));
      await tester.pumpAndSettle();
      await tester.tap(find.text('설정'));
      await tester.pumpAndSettle();
      final safety = find.widgetWithText(SwitchListTile, '안전 이상 알림');
      await tester.scrollUntilVisible(
        safety,
        300,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.ensureVisible(safety);
      expect(tester.widget<SwitchListTile>(safety).onChanged, isNull);
      expect(find.text('알림 설정을 불러오지 못했어요'), findsOneWidget);
      repository.failPreferencesLoad = false;
      await tester.ensureVisible(find.text('설정 재시도'));
      await tester.tap(find.text('설정 재시도'));
      await tester.pumpAndSettle();
      expect(tester.widget<SwitchListTile>(safety).value, isTrue);
      expect(tester.widget<SwitchListTile>(safety).onChanged, isNotNull);
      repository.failPreferencesSave = true;
      await tester.ensureVisible(safety);
      await tester.tap(safety);
      await tester.pumpAndSettle();
      expect(tester.widget<SwitchListTile>(safety).value, isTrue);
      expect(repository.preferences.safetyNotifications, isTrue);
      expect(find.text('알림 설정을 저장하지 못했습니다.'), findsOneWidget);
      repository.failPreferencesSave = false;
      await tester.tap(safety);
      await tester.pumpAndSettle();
      expect(repository.preferences.safetyNotifications, isFalse);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pumpWidget(PauseableApp(repository: repository));
      await tester.pumpAndSettle();
      await tester.tap(find.text('설정'));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        safety,
        300,
        scrollable: find.byType(Scrollable).first,
      );
      expect(tester.widget<SwitchListTile>(safety).value, isFalse);
      expect(repository.snapshot.doorEvents, snapshot.doorEvents);
    },
  );

  for (final enabled in [true, false]) {
    testWidgets(
      'live alert popup follows saved preference while history still updates ($enabled)',
      (tester) async {
        final repository = _MemoryGuardianRepository(snapshot)
          ..preferences = GuardianPreferences(
            safetyNotifications: enabled,
            soundEnabled: false,
          );
        final client = _PreferenceLiveClient();
        addTearDown(() {
          unawaited(client.dispose());
        });
        await tester.pumpWidget(
          PauseableApp(repository: repository, liveAlertClient: client),
        );
        await tester.pumpAndSettle();

        repository.failPreferencesLoad = !enabled;
        client.controller.add(
          LiveAppAlert(
            id: 'prefs-repeat-$enabled',
            occurredAt: DateTime.utc(2026, 10, 23),
            riskLevel: 'caution',
            alertType: 'repetitive_behavior',
            title: '설정 시험 반복행동',
            message: '기록은 계속 갱신됩니다.',
          ),
        );
        await tester.pumpAndSettle();
        expect(
          find.text('새 실시간 알림 · 설정 시험 반복행동'),
          enabled ? findsOneWidget : findsNothing,
        );
        await tester.tap(find.text('알림').last);
        await tester.pumpAndSettle();
        expect(find.text('설정 시험 반복행동'), findsOneWidget);
        expect(repository.snapshot.doorEvents, snapshot.doorEvents);
        await tester.pumpWidget(const SizedBox.shrink());
        await tester.pumpAndSettle();
      },
    );
  }

  testWidgets('caregiver can pause a repeated behavior alert', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      PauseableApp(repository: _MemoryGuardianRepository(snapshot)),
    );
    await tester.pumpAndSettle();

    await tester.scrollUntilVisible(
      find.text('반복 행동 확인 필요'),
      400,
      scrollable: find.byType(Scrollable).first,
    );

    expect(find.text('반복 행동 확인 필요'), findsOneWidget);
    await tester.ensureVisible(find.text('정상으로 확인'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('정상으로 확인'));
    await tester.pumpAndSettle();

    expect(find.text('정상 상황으로 확인할까요?'), findsOneWidget);
    await tester.tap(find.text('1시간 동안 알림 중지'));
    await tester.pumpAndSettle();

    expect(find.text('반복 행동 알림 일시 중지됨'), findsOneWidget);
    expect(find.text('알림 다시 켜기'), findsOneWidget);

    await tester.tap(find.text('알림'));
    await tester.pumpAndSettle();
    expect(find.text('알림 중지 중'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets(
    'saved pause survives reopening, resumes and expires without blocking photos',
    (tester) async {
      final repository = _MemoryGuardianRepository(snapshot);
      repository._setPause(DateTime.now().add(const Duration(minutes: 30)));
      Future<void> open() async {
        await tester.pumpWidget(PauseableApp(repository: repository));
        await tester.pumpAndSettle();
        await tester.scrollUntilVisible(
          find.byKey(const ValueKey('home-behavior-alert')),
          400,
          scrollable: find.byType(Scrollable).first,
        );
      }

      await open();
      expect(find.text('반복 행동 알림 일시 중지됨'), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
      await open();
      expect(find.text('반복 행동 알림 일시 중지됨'), findsOneWidget);
      await tester.ensureVisible(find.text('알림 다시 켜기'));
      await tester.tap(find.text('알림 다시 켜기'));
      await tester.pumpAndSettle();
      expect(repository.snapshot.repetitiveAlertsPaused, isFalse);
      expect(
        repository.snapshot.doorEvents,
        hasLength(snapshot.doorEvents.length),
      );
      await tester.pumpWidget(const SizedBox.shrink());
      repository._setPause(DateTime.now().add(const Duration(seconds: 2)));
      await open();
      repository._setPause(DateTime.now().subtract(const Duration(seconds: 1)));
      await tester.pump(const Duration(seconds: 3));
      await tester.pumpAndSettle();
      expect(find.text('반복 행동 알림 일시 중지됨'), findsNothing);
      expect(find.text('정상으로 확인'), findsWidgets);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  testWidgets(
    'failed pause save never claims that notifications have stopped',
    (tester) async {
      final repository = _MemoryGuardianRepository(snapshot)
        ..failPauseSave = true;
      tester.view.physicalSize = const Size(800, 1400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(PauseableApp(repository: repository));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.byKey(const ValueKey('home-behavior-alert')),
        400,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.ensureVisible(find.text('정상으로 확인'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('정상으로 확인'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('1시간 동안 알림 중지'));
      await tester.pumpAndSettle();
      expect(find.text('반복 행동 알림 일시 중지됨'), findsNothing);
      expect(find.textContaining('알림 중지 상태를 확인하지 못했습니다.'), findsOneWidget);
      expect(repository.snapshot.repetitiveAlertsPaused, isFalse);
    },
  );

  testWidgets('door alert reloads a missing photo and opens its scene', (
    tester,
  ) async {
    final event = snapshot.doorEvents.first;
    final repository = _MemoryGuardianRepository(snapshot)
      ..alertHistory = [
        LiveAppAlert(
          id: 'door-camera-new',
          occurredAt: DateTime.utc(2026, 10, 6),
          riskLevel: 'caution',
          alertType: 'door_event',
          title: '새 현관 사진 알림',
          message: '새 장면을 확인해 주세요.',
          relatedEventId: 'camera-new',
        ),
      ];
    await tester.pumpWidget(PauseableApp(repository: repository));
    await tester.pumpAndSettle();
    repository.snapshot = GuardianSnapshot(
      patient: snapshot.patient,
      alerts: snapshot.alerts,
      activity: snapshot.activity,
      demoScenario: snapshot.demoScenario,
      doorEvents: [
        DoorEvent(
          id: 'camera-new',
          occurredAt: DateTime.utc(2026, 10, 6),
          timeLabel: '10월 6일 09:00',
          direction: DoorEventDirection.unknown,
          title: '새 촬영 사진 상세',
          description: '방금 도어락 이벤트에서 촬영된 사진입니다.',
          imageUrl: event.imageUrl,
          isConfirmed: false,
        ),
      ],
    );
    await tester.tap(find.text('알림'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('새 현관 사진 알림'));
    await tester.pumpAndSettle();
    expect(repository.markedReadIds, ['door-camera-new']);
    expect(find.text('새 촬영 사진 상세'), findsWidgets);
    expect(find.text('이 장면 확인 완료'), findsOneWidget);
    expect(find.text('확인했습니다'), findsNothing);
  });

  testWidgets('caregiver can inspect and confirm a door event', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      PauseableApp(repository: _MemoryGuardianRepository(snapshot)),
    );
    await tester.pumpAndSettle();

    await tester.scrollUntilVisible(
      find.text('장면 확인하기'),
      400,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.ensureVisible(find.text('장면 확인하기'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('장면 확인하기'));
    await tester.pumpAndSettle();

    expect(find.text('인상착의'), findsNothing);
    expect(find.text('현관문이 열리고 외출하는 장면이 촬영됐어요.'), findsOneWidget);
    await tester.ensureVisible(find.text('사진 크게 보기 · 확대'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('사진 크게 보기 · 확대'));
    await tester.pumpAndSettle();

    final viewer = tester.widget<InteractiveViewer>(
      find.byType(InteractiveViewer),
    );
    final photoCenter = tester.getCenter(find.byType(InteractiveViewer));
    expect(viewer.transformationController!.value.getMaxScaleOnAxis(), 1);
    await tester.tapAt(photoCenter);
    await tester.pump(const Duration(milliseconds: 100));
    await tester.tapAt(photoCenter);
    await tester.pumpAndSettle();
    expect(viewer.transformationController!.value.getMaxScaleOnAxis(), 3);
    await tester.tap(find.byTooltip('사진 전체 보기'));
    await tester.pumpAndSettle();
    expect(viewer.transformationController!.value.getMaxScaleOnAxis(), 1);
    await tester.tap(find.byTooltip('사진 닫기'));
    await tester.pumpAndSettle();

    await tester.ensureVisible(find.text('이 장면 확인 완료'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('이 장면 확인 완료'));
    await tester.pumpAndSettle();

    expect(find.text('확인 완료'), findsOneWidget);
  });

  testWidgets('caregiver can activate a demo scenario', (
    WidgetTester tester,
  ) async {
    final repository = _MemoryGuardianRepository(snapshot);
    await tester.pumpWidget(PauseableApp(repository: repository));
    await tester.pumpAndSettle();

    await tester.tap(find.text('설정'));
    await tester.pumpAndSettle();
    final inactivityTile = find.widgetWithText(ListTile, '장시간 무활동');
    await tester.scrollUntilVisible(
      inactivityTile,
      300,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.pumpAndSettle();
    await tester.tap(inactivityTile);
    await tester.pumpAndSettle();

    expect(repository.activatedScenarioIds, ['inactivity']);
    expect(find.text('장시간 무활동 시나리오를 적용했습니다.'), findsOneWidget);
  });

  testWidgets('caregiver can record and upload a guardian voice message', (
    WidgetTester tester,
  ) async {
    final repository = _MemoryGuardianRepository(snapshot);
    await tester.pumpWidget(
      PauseableApp(
        repository: repository,
        voiceRecorderFactory: _FakeVoiceRecorder.new,
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('보호자 목소리 학습이 필요해요'), findsOneWidget);
    expect(find.text('100 / 800초 권장'), findsOneWidget);
    expect(
      find.text('800초는 권장 기준이며 녹음이 많을수록 TTS 품질 향상에 도움이 돼요.'),
      findsOneWidget,
    );
    expect(find.text('음성 학습'), findsNothing);

    await tester.tap(find.text('이어서 녹음'));
    await tester.pumpAndSettle();
    await _acceptVoiceConsent(tester);

    expect(find.text('보호자 목소리 학습'), findsOneWidget);
    expect(find.text('조용한 곳에서 녹음해 주세요'), findsOneWidget);
    expect(find.text('100 / 800초 권장'), findsWidgets);
    expect(find.text('문장 3 / 160'), findsOneWidget);
    expect(find.text('S003.wav'), findsOneWidget);
    expect(find.text('노란 개나리 옆에 분홍 진달래가 피었어요.'), findsOneWidget);
    await tester.ensureVisible(find.text('이 문장 녹음 시작'));
    await tester.tap(find.text('이 문장 녹음 시작'));
    await tester.pump();
    expect(find.text('문장을 읽어 주세요'), findsOneWidget);

    await tester.tap(find.text('이 문장 녹음 완료 · 자동 전송'));
    await tester.pumpAndSettle();

    expect(repository.voiceUploadCount, 1);
    expect(repository.lastVoiceFileName, 'S003.wav');
    expect(repository.lastVoiceDurationSeconds, 2);
    expect(repository.lastVoicePromptText, '노란 개나리 옆에 분홍 진달래가 피었어요.');
    expect(find.text('102 / 800초 권장'), findsOneWidget);
    expect(find.text('S003.wav 저장 완료 · 누적 102초예요.'), findsOneWidget);

    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpAndSettle();
  });

  testWidgets('recommended voice training can continue beyond 800 seconds', (
    WidgetTester tester,
  ) async {
    final repository = _MemoryGuardianRepository(snapshot)
      ..voiceProgress = const VoiceTrainingProgress(
        targetSeconds: 800,
        recordedSeconds: 950,
        clipCount: 150,
        isReady: true,
      );

    await tester.pumpWidget(
      PauseableApp(
        key: UniqueKey(),
        repository: repository,
        voiceRecorderFactory: _FakeVoiceRecorder.new,
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('권장 녹음 분량 달성'), findsOneWidget);
    expect(find.text('950초 녹음됨 · 더 녹음하면 TTS 품질이 높아져요.'), findsOneWidget);
    expect(find.text('추가 녹음'), findsOneWidget);
    expect(find.text('음성 학습'), findsNothing);
  });

  testWidgets(
    'new voice training confirms preserves the old voice and starts at S001',
    (tester) async {
      final repository = _MemoryGuardianRepository(snapshot)
        ..voiceProgress = const VoiceTrainingProgress(
          targetSeconds: 800,
          recordedSeconds: 976,
          clipCount: 160,
          isReady: true,
          jobId: 'voice-job-111111111111',
          jobStatus: 'completed',
        );
      await tester.pumpWidget(
        PauseableApp(
          repository: repository,
          voiceRecorderFactory: _FakeVoiceRecorder.new,
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('음성 학습 완료'), findsOneWidget);
      expect(find.text('추가 녹음'), findsNothing);
      await tester.tap(find.text('음성 학습 관리'));
      await tester.pumpAndSettle();
      await _acceptVoiceConsent(tester);
      expect(find.text('이 문장 녹음 시작'), findsNothing);
      final start = find.text('새 음성학습 시작');
      await tester.ensureVisible(start);
      await tester.pumpAndSettle();
      await tester.tap(start);
      await tester.pumpAndSettle();
      expect(find.textContaining('현재 사용하는 목소리는 유지하고'), findsOneWidget);
      await tester.tap(find.text('취소'));
      await tester.pumpAndSettle();
      expect(repository.newTrainingCount, 0);
      expect(repository.voiceProgress.clipCount, 160);
      await tester.tap(start);
      await tester.pumpAndSettle();
      await tester.tap(find.text('새 학습 시작'));
      await tester.pumpAndSettle();
      expect(repository.newTrainingCount, 1);
      expect(repository.installedVoiceVersion, 'existing-trained-voice');
      expect(find.text('문장 1 / 160'), findsOneWidget);
      expect(repository.voiceProgress.recordedSeconds, 0);
      await tester.ensureVisible(find.text('이 문장 녹음 시작'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('이 문장 녹음 시작'));
      await tester.pump();
      await tester.ensureVisible(find.text('이 문장 녹음 완료 · 자동 전송'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('이 문장 녹음 완료 · 자동 전송'));
      await tester.pumpAndSettle();
      expect(repository.lastVoiceFileName, 'S001.wav');
      expect(repository.lastTrainingJobId, 'voice-job-222222222222');
      expect(repository.voiceProgress.clipCount, 1);
      expect(repository.installedVoiceVersion, 'existing-trained-voice');
    },
  );

  testWidgets(
    'failed new voice session keeps the completed set and can retry',
    (tester) async {
      final repository = _MemoryGuardianRepository(snapshot)
        ..failNewTraining = true
        ..voiceProgress = const VoiceTrainingProgress(
          targetSeconds: 800,
          recordedSeconds: 976,
          clipCount: 160,
          isReady: true,
          jobId: 'voice-job-111111111111',
          jobStatus: 'completed',
        );
      await tester.pumpWidget(PauseableApp(repository: repository));
      await tester.pumpAndSettle();
      await tester.tap(find.text('음성 학습 관리'));
      await tester.pumpAndSettle();
      await _acceptVoiceConsent(tester);
      await tester.ensureVisible(find.text('새 음성학습 시작'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('새 음성학습 시작'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('새 학습 시작'));
      await tester.pumpAndSettle();
      expect(find.textContaining('새 학습 세트를 시작하지 못했습니다'), findsOneWidget);
      expect(repository.newTrainingCount, 0);
      expect(repository.voiceProgress.jobId, 'voice-job-111111111111');
      expect(repository.voiceProgress.clipCount, 160);
      expect(repository.installedVoiceVersion, 'existing-trained-voice');
      repository.failNewTraining = false;
      await tester.ensureVisible(find.text('새 음성학습 시작'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('새 음성학습 시작'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('새 학습 시작'));
      await tester.pumpAndSettle();
      expect(repository.newTrainingCount, 1);
      expect(find.text('문장 1 / 160'), findsOneWidget);
    },
  );

  testWidgets('queued training cannot record or create another set', (
    tester,
  ) async {
    final repository = _MemoryGuardianRepository(snapshot)
      ..voiceProgress = const VoiceTrainingProgress(
        targetSeconds: 800,
        recordedSeconds: 700,
        clipCount: 160,
        isReady: false,
        jobId: 'voice-job-111111111111',
        jobStatus: 'queued',
      );
    await tester.pumpWidget(PauseableApp(repository: repository));
    await tester.pumpAndSettle();
    expect(find.text('학습 대기 중'), findsOneWidget);
    await tester.tap(find.text('음성 학습 관리'));
    await tester.pumpAndSettle();
    await _acceptVoiceConsent(tester);
    expect(find.text('새 음성학습 시작'), findsNothing);
    expect(find.text('이 문장 녹음 시작'), findsNothing);
    expect(find.text('학습 상태 새로고침'), findsOneWidget);
    expect(repository.newTrainingCount, 0);
  });

  testWidgets('home navigation and virtual contact buttons are active', (
    WidgetTester tester,
  ) async {
    final repository = _MemoryGuardianRepository(snapshot);
    await tester.pumpWidget(PauseableApp(repository: repository));
    await tester.pumpAndSettle();

    await tester.tap(
      find.widgetWithIcon(IconButton, Icons.notifications_none_rounded),
    );
    await tester.pumpAndSettle();
    expect(find.text('알림 센터'), findsOneWidget);

    await tester.tap(find.text('홈'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('전화 걸기'),
      500,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('전화 걸기'));
    await tester.pumpAndSettle();
    expect(find.text('보호 전화를 연결할까요?'), findsOneWidget);
    await tester.tap(find.text('전화 요청'));
    await tester.pumpAndSettle();
    expect(repository.careCallCount, 1);
    expect(find.text('보호 전화 요청 완료'), findsOneWidget);
    await tester.tap(find.text('확인'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('긴급 연락'));
    await tester.pumpAndSettle();
    expect(find.text('긴급 연락을 요청할까요?'), findsOneWidget);
    await tester.tap(find.text('긴급 요청'));
    await tester.pumpAndSettle();
    expect(repository.emergencyContactCount, 1);
    expect(find.text('긴급 연락 요청 완료'), findsOneWidget);
  });

  testWidgets('saved names update home and alerts and survive reopening', (
    tester,
  ) async {
    final repository = _MemoryGuardianRepository(snapshot);
    final patientId = snapshot.patient.id;
    await tester.pumpWidget(PauseableApp(repository: repository));
    await tester.pumpAndSettle();
    await tester.tap(find.text('설정'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('김보호님'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('guardian-name-field')),
      '  박지수  ',
    );
    await tester.enterText(
      find.byKey(const ValueKey('patient-name-field')),
      '  홍길동  ',
    );
    await tester.tap(find.text('저장'));
    await tester.pumpAndSettle();
    expect(find.text('박지수님'), findsOneWidget);
    expect(find.text('홍길동님'), findsOneWidget);
    expect(repository.guardianProfile.name, '박지수');
    expect(repository.guardianProfile.patientName, '홍길동');
    expect(repository.snapshot.patient.id, patientId);
    await tester.tap(find.text('홈'));
    await tester.pumpAndSettle();
    expect(find.text('안녕하세요, 박지수님'), findsOneWidget);
    expect(find.text('홍길동님'), findsOneWidget);
    await tester.tap(find.text('알림').last);
    await tester.pumpAndSettle();
    expect(find.textContaining('홍길동님의 최근 감지 내역'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpWidget(PauseableApp(repository: repository));
    await tester.pumpAndSettle();
    expect(find.text('안녕하세요, 박지수님'), findsOneWidget);
    expect(find.text('홍길동님'), findsOneWidget);
  });

  testWidgets(
    'empty names validate and failed saves preserve input for retry',
    (tester) async {
      final repository = _MemoryGuardianRepository(snapshot)
        ..guardianProfile = const GuardianProfile(
          name: '',
          relationship: '',
          phoneNumber: '',
        )
        ..failProfileSave = true;
      await tester.pumpWidget(PauseableApp(repository: repository));
      await tester.pumpAndSettle();
      expect(find.text('안녕하세요, 보호자님'), findsOneWidget);
      expect(find.text('김영희 님'), findsNothing);
      await tester.tap(find.text('정보 등록'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('저장'));
      await tester.pumpAndSettle();
      expect(find.text('이름을 입력해 주세요.'), findsNWidgets(2));
      await tester.enterText(
        find.byKey(const ValueKey('guardian-name-field')),
        '박지수',
      );
      await tester.enterText(
        find.byKey(const ValueKey('patient-name-field')),
        '홍길동',
      );
      await tester.tap(find.text('저장'));
      await tester.pumpAndSettle();
      expect(find.textContaining('저장하지 못했어요.'), findsOneWidget);
      expect(repository.guardianProfile.name, isEmpty);
      repository.failProfileSave = false;
      await tester.tap(find.text('저장'));
      await tester.pumpAndSettle();
      expect(find.byType(AlertDialog), findsNothing);
      expect(find.text('안녕하세요, 박지수님'), findsOneWidget);
      expect(find.text('정보 등록'), findsNothing);
    },
  );

  testWidgets(
    'profile load retries without blocking alerts or showing fake names',
    (tester) async {
      final repository = _MemoryGuardianRepository(snapshot)
        ..failProfileLoad = true;
      await tester.pumpWidget(PauseableApp(repository: repository));
      await tester.pumpAndSettle();
      expect(find.text('돌봄 정보를 불러오지 못했어요'), findsOneWidget);
      expect(find.text('안녕하세요, 보호자님'), findsOneWidget);
      await tester.tap(find.text('알림').last);
      await tester.pumpAndSettle();
      expect(find.textContaining('돌봄 대상자의 최근 감지 내역'), findsOneWidget);
      await tester.tap(find.text('홈'));
      await tester.pumpAndSettle();
      repository.failProfileLoad = false;
      await tester.tap(find.text('재시도'));
      await tester.pumpAndSettle();
      expect(find.text('안녕하세요, 김보호님'), findsOneWidget);
    },
  );

  testWidgets('family relation and editable TTS name survive a reload', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(800, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final repository = _MemoryGuardianRepository(snapshot);
    await tester.pumpWidget(PauseableApp(repository: repository));
    await tester.pumpAndSettle();
    await tester.tap(find.text('설정'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('family-tts-settings')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('guardian-relationship-field')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('딸').last);
    await tester.pumpAndSettle();
    final callName = find.byKey(const ValueKey('patient-call-name-field'));
    await tester.ensureVisible(callName);

    expect(tester.widget<TextFormField>(callName).controller!.text, isEmpty);
    await tester.ensureVisible(find.widgetWithText(ActionChip, '엄마'));
    await tester.tap(find.widgetWithText(ActionChip, '엄마'));
    await tester.pumpAndSettle();
    expect(find.textContaining('엄마, 잠깐 쉬었다가 해요.'), findsOneWidget);
    await tester.enterText(callName, '어머니');
    repository.failProfileSave = true;
    await tester.tap(find.text('저장'));
    await tester.pumpAndSettle();
    expect(repository.guardianProfile.patientCallName, isEmpty);
    expect(find.textContaining('저장하지 못했어요.'), findsOneWidget);
    repository.failProfileSave = false;
    await tester.tap(find.text('저장'));
    await tester.pumpAndSettle();
    expect(repository.guardianProfile.relationship, '딸');
    expect(repository.guardianProfile.patientCallName, '어머니');
    expect(find.text('부르는 호칭 · 어머니'), findsOneWidget);
    expect(repository.voiceProgress.clipCount, 2);
    expect(repository.snapshot.doorEvents, snapshot.doorEvents);
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpWidget(PauseableApp(repository: repository));
    await tester.pumpAndSettle();
    await tester.tap(find.text('설정'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('family-tts-settings')));
    await tester.pumpAndSettle();
    expect(tester.widget<TextFormField>(callName).controller!.text, '어머니');

    await tester.tap(find.byKey(const ValueKey('guardian-relationship-field')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('손자').last);
    await tester.pumpAndSettle();
    expect(tester.widget<TextFormField>(callName).controller!.text, '어머니');
    await tester.ensureVisible(find.widgetWithText(ActionChip, '할머니'));
    await tester.tap(find.widgetWithText(ActionChip, '할머니'));
    await tester.tap(find.text('저장'));
    await tester.pumpAndSettle();
    expect(repository.guardianProfile.patientCallName, '할머니');
    await tester.tap(find.byKey(const ValueKey('family-tts-settings')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(callName);
    await tester.enterText(callName, '');
    await tester.tap(find.text('취소'));
    await tester.pumpAndSettle();
    expect(repository.guardianProfile.patientCallName, '할머니');
  });

  testWidgets('settings cards and device connection check are active', (
    WidgetTester tester,
  ) async {
    final repository = _MemoryGuardianRepository(snapshot);
    await tester.pumpWidget(PauseableApp(repository: repository));
    await tester.pumpAndSettle();

    await tester.tap(find.text('설정'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('김보호님'));
    await tester.pumpAndSettle();
    expect(find.text('보호자·대상자 정보 수정'), findsOneWidget);
    await tester.tap(find.text('취소'));
    await tester.pumpAndSettle();

    await tester.scrollUntilVisible(
      find.text('연결된 기기'),
      500,
      scrollable: find.byType(Scrollable).first,
    );
    final connectedDevices = find.widgetWithText(ListTile, '연결된 기기');
    await tester.drag(find.byType(Scrollable).first, const Offset(0, -220));
    await tester.pumpAndSettle();
    await tester.tap(connectedDevices);
    await tester.pumpAndSettle();
    expect(find.text('Home Assistant'), findsOneWidget);
    expect(find.text('현관 센서·카메라'), findsOneWidget);
    await tester.tap(find.text('연결 다시 확인'));
    await tester.pumpAndSettle();
    expect(repository.deviceCheckCount, 1);

    await tester.scrollUntilVisible(
      find.text('앱 정보'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    final appInfo = find.widgetWithText(ListTile, '앱 정보');
    await tester.drag(find.byType(Scrollable).first, const Offset(0, -150));
    await tester.pumpAndSettle();
    await tester.tap(appInfo);
    await tester.pumpAndSettle();
    expect(find.text('PAUSEABLE 보호자'), findsOneWidget);
    expect(find.text('1.0.0 (데모)'), findsOneWidget);
  });

  testWidgets('guardian can save and remove a favorite YouTube song', (
    WidgetTester tester,
  ) async {
    tester.view.physicalSize = const Size(800, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final repository = _MemoryGuardianRepository(snapshot);
    await tester.pumpWidget(
      MaterialApp(home: FavoriteSongsPage(repository: repository)),
    );
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField).at(0), '좋아하는 노래');
    await tester.enterText(
      find.byType(TextField).at(1),
      'https://youtu.be/dQw4w9WgXcQ',
    );
    await tester.tap(find.text('노래 추가'));
    await tester.pumpAndSettle();
    expect(repository.favoriteSongs.single.videoId, 'dQw4w9WgXcQ');
    expect(find.text('등록된 노래 1/30'), findsOneWidget);

    await tester.tap(find.byTooltip('좋아하는 노래 삭제'));
    await tester.pumpAndSettle();
    expect(repository.favoriteSongs, isEmpty);
    expect(find.text('등록된 노래 0/30'), findsOneWidget);
  });
}

class _TestPushBrowser implements WebPushBrowser {
  bool subscribed = false;

  @override
  bool get isSupported => true;

  @override
  String get permission => subscribed ? 'granted' : 'default';

  @override
  Future<String?> currentSubscription() async => subscribed
      ? '{"endpoint":"https://fcm.googleapis.com/fcm/send/test",'
            '"keys":{"p256dh":"test","auth":"test"}}'
      : null;

  @override
  Future<String> subscribe(String publicKey) async {
    expect(publicKey, 'test-public-key');
    subscribed = true;
    return (await currentSubscription())!;
  }

  @override
  Future<bool> unsubscribe() async {
    subscribed = false;
    return true;
  }
}

class _PreferenceLiveClient implements LiveAlertClient {
  final controller = StreamController<LiveAppAlert>.broadcast();
  @override
  Stream<LiveAppAlert> get alerts => controller.stream;
  @override
  Stream<LiveAlertConnectionStatus> get statuses => const Stream.empty();
  @override
  void start() {}
  @override
  Future<void> dispose() => controller.close();
}

class _ConnectedHomeLiveClient extends _PreferenceLiveClient {
  @override
  Stream<LiveAlertConnectionStatus> get statuses =>
      Stream.value(LiveAlertConnectionStatus.connected);
}

class _MemoryGuardianRepository implements GuardianRepository {
  int consentSaveCount = 0;
  bool failConsentSave = false;
  final consentRequestIds = <String>[];

  @override
  Future<VoiceConsentReceipt> saveVoiceConsent({
    required String requestId,
  }) async {
    consentSaveCount++;
    consentRequestIds.add(requestId);
    if (failConsentSave) throw Exception('offline');
    return VoiceConsentReceipt(
      consentId: 'voice-consent-$requestId',
      patientId: 'byunwoojin',
      policyVersion: VoiceConsentReceipt.currentPolicyVersion,
      acceptedAt: DateTime.now().toUtc(),
    );
  }

  bool failPreferencesLoad = false;
  bool failPreferencesSave = false;
  Uint8List? photoBytes;
  bool failPhotoLoad = false;
  int photoLoadCount = 0;

  @override
  Future<Uint8List> loadDoorPhoto({required String eventId}) async {
    photoLoadCount++;
    if (failPhotoLoad) throw StateError('Temporary photo request failure');
    return photoBytes ??
        await MockGuardianRepository().loadDoorPhoto(eventId: eventId);
  }

  _MemoryGuardianRepository(this.snapshot);

  List<LiveAppAlert> alertHistory = [];
  final List<String> markedReadIds = [];

  @override
  Future<List<LiveAppAlert>> loadAlertHistory() async => List.of(alertHistory);

  @override
  Future<void> markAlertRead(String alertId) async {
    markedReadIds.add(alertId);
  }

  List<FavoriteSong> favoriteSongs = [];

  @override
  Future<List<FavoriteSong>> loadFavoriteSongs() async =>
      List.of(favoriteSongs);

  @override
  Future<List<FavoriteSong>> saveFavoriteSongs(List<FavoriteSong> songs) async {
    favoriteSongs = List.of(songs);
    return List.of(favoriteSongs);
  }

  HomeEnvironment homeEnvironment = const HomeEnvironment(
    region: HomeRegion(
      code: '1111051500',
      province: '서울특별시',
      city: '종로구',
      district: '청운효자동',
      nx: 60,
      ny: 127,
      latitude: 37.5841367,
      longitude: 126.9706519,
    ),
    lightingStatus: 'disabled',
  );
  bool failHomeSave = false;
  bool failVoiceUpload = false;
  bool failNewTraining = false;
  int newTrainingCount = 0;
  String? lastTrainingJobId;
  final String installedVoiceVersion = 'existing-trained-voice';

  @override
  Future<HomeEnvironment> loadHomeEnvironment() async => homeEnvironment;

  @override
  Future<HomeEnvironment> updateHomeEnvironment({
    required String regionCode,
    required bool autoLightingEnabled,
  }) async {
    if (failHomeSave) throw Exception('offline');
    final regions = await HomeRegionCatalog.load();
    return homeEnvironment = HomeEnvironment(
      region: regions.firstWhere((r) => r.code == regionCode),
      autoLightingEnabled: autoLightingEnabled,
      lightingStatus: autoLightingEnabled ? 'awaiting_integration' : 'disabled',
    );
  }

  GuardianSnapshot snapshot;
  final List<String> activatedScenarioIds = [];
  int voiceUploadCount = 0;
  int voiceUploadAttempts = 0;
  String? lastVoiceFileName;
  int? lastVoiceDurationSeconds;
  String? lastVoicePromptText;
  VoiceTrainingProgress voiceProgress = const VoiceTrainingProgress(
    targetSeconds: 800,
    recordedSeconds: 100,
    clipCount: 2,
    isReady: false,
  );
  int careCallCount = 0;
  int emergencyContactCount = 0;
  int deviceCheckCount = 0;
  GuardianProfile guardianProfile = const GuardianProfile(
    name: '김보호',
    patientName: '김영희',
    relationship: '김영희 님의 보호자',
    phoneNumber: '010-1234-5678',
  );
  bool failProfileSave = false;
  bool failProfileLoad = false;
  GuardianPreferences preferences = const GuardianPreferences(
    safetyNotifications: true,
    soundEnabled: false,
  );

  @override
  Future<GuardianSnapshot> loadSnapshot() async => snapshot;

  bool failPauseSave = false;

  @override
  Future<void> pauseAlert({
    required String alertId,
    required Duration duration,
  }) async {
    if (failPauseSave) throw StateError('Pause storage unavailable');
    _setPause(DateTime.now().add(duration));
  }

  @override
  Future<void> resumeAlert({required String alertId}) async {
    _setPause(null);
  }

  void _setPause(DateTime? until) {
    snapshot = GuardianSnapshot(
      patient: snapshot.patient,
      alerts: snapshot.alerts,
      activity: snapshot.activity,
      doorEvents: snapshot.doorEvents,
      demoScenario: snapshot.demoScenario,
      repetitiveAlertPauseAvailable: true,
      repetitiveAlertPauseUntil: until,
    );
  }

  @override
  Future<void> confirmDoorEvent({required String eventId}) async {}

  @override
  Future<void> activateDemoScenario({required String scenarioId}) async {
    activatedScenarioIds.add(scenarioId);
  }

  @override
  Future<GuardianProfile> loadGuardianProfile() async {
    if (failProfileLoad) throw StateError('profile unavailable');
    return guardianProfile;
  }

  @override
  Future<GuardianProfile> updateGuardianProfile({
    required String name,
    required String patientName,
    required String relationship,
    required String phoneNumber,
    String? patientCallName,
  }) async {
    if (failProfileSave) throw StateError('profile save unavailable');
    guardianProfile = GuardianProfile(
      name: name,
      patientName: patientName,
      relationship: relationship,
      phoneNumber: phoneNumber,
      patientCallName: patientCallName ?? guardianProfile.patientCallName,
    );
    return guardianProfile;
  }

  @override
  Future<GuardianPreferences> loadPreferences() async {
    if (failPreferencesLoad) {
      throw StateError('Settings temporarily unavailable');
    }
    return preferences;
  }

  @override
  Future<GuardianPreferences> updatePreferences({
    required bool safetyNotifications,
    required bool soundEnabled,
  }) async {
    if (failPreferencesSave) throw StateError('Settings could not be saved');
    preferences = GuardianPreferences(
      safetyNotifications: safetyNotifications,
      soundEnabled: soundEnabled,
    );
    return preferences;
  }

  @override
  Future<DeviceConnectionStatus> loadDeviceConnection() async =>
      _memoryDeviceConnection;

  @override
  Future<DeviceConnectionStatus> checkDeviceConnection() async {
    deviceCheckCount++;
    return _memoryDeviceConnection;
  }

  @override
  Future<GuardianActionResult> requestCareCall() async {
    careCallCount++;
    return const GuardianActionResult(
      title: '보호 전화 요청 완료',
      message: '가상 보호 전화 요청을 보냈습니다.',
      referenceId: 'test-care-001',
    );
  }

  @override
  Future<GuardianActionResult> requestEmergencyContact() async {
    emergencyContactCount++;
    return const GuardianActionResult(
      title: '긴급 연락 요청 완료',
      message: '가상 긴급 연락 요청을 보냈습니다.',
      referenceId: 'test-emergency-001',
    );
  }

  @override
  Future<void> uploadVoiceMessage({
    required Uint8List audioBytes,
    required String fileName,
    required int durationSeconds,
  }) async {
    voiceUploadCount++;
    lastVoiceFileName = fileName;
    lastVoiceDurationSeconds = durationSeconds;
  }

  @override
  Future<VoiceTrainingProgress> loadVoiceTrainingProgress() async =>
      voiceProgress;

  @override
  Future<VoiceTrainingProgress> startNewVoiceTraining({
    required String previousJobId,
  }) async {
    if (failNewTraining) throw Exception('offline');
    if (!voiceProgress.canStartNewTraining ||
        voiceProgress.jobId != previousJobId) {
      throw StateError('session changed');
    }
    newTrainingCount++;
    return voiceProgress = const VoiceTrainingProgress(
      targetSeconds: 800,
      recordedSeconds: 0,
      clipCount: 0,
      isReady: false,
      jobId: 'voice-job-222222222222',
    );
  }

  @override
  Future<VoiceTrainingProgress> uploadVoiceTrainingClip({
    required Uint8List audioBytes,
    required String fileName,
    required int durationSeconds,
    required String promptText,
    String? jobId,
  }) async {
    voiceUploadAttempts++;
    if (failVoiceUpload) throw Exception('offline');
    voiceUploadCount++;
    lastVoiceFileName = fileName;
    lastVoiceDurationSeconds = durationSeconds;
    lastVoicePromptText = promptText;
    lastTrainingJobId = jobId;
    voiceProgress = VoiceTrainingProgress(
      targetSeconds: 800,
      recordedSeconds: voiceProgress.recordedSeconds + durationSeconds,
      clipCount: voiceProgress.clipCount + 1,
      isReady: voiceProgress.recordedSeconds + durationSeconds >= 800,
      jobId: voiceProgress.jobId,
      jobStatus: voiceProgress.jobStatus,
    );
    return voiceProgress;
  }
}

const _memoryDeviceConnection = DeviceConnectionStatus(
  deviceName: 'PAUSEABLE Home',
  isOnline: true,
  lastCheckedLabel: '방금 전',
  services: [
    DeviceServiceStatus(
      name: 'Home Assistant',
      isConnected: true,
      detail: '가상 센서 데이터 수신 중',
    ),
    DeviceServiceStatus(
      name: '현관 센서·카메라',
      isConnected: true,
      detail: '가상 출입 이벤트 사용 중',
    ),
    DeviceServiceStatus(
      name: 'Raspberry Pi 5',
      isConnected: true,
      detail: '가상 연결 상태',
    ),
  ],
);

Future<void> _acceptVoiceConsent(WidgetTester tester) async {
  final checkbox = find.byKey(const ValueKey('voice-consent-checkbox'));
  await tester.ensureVisible(checkbox);
  await tester.pumpAndSettle();
  await tester.tap(checkbox);
  await tester.pumpAndSettle();
  final next = find.byKey(const ValueKey('voice-consent-continue'));
  await tester.ensureVisible(next);
  await tester.pumpAndSettle();
  await tester.tap(next);
  await tester.pumpAndSettle();
}

class _FakeVoiceRecorder implements VoiceRecordingService {
  @override
  Future<bool> start() async => true;

  @override
  Future<VoiceRecording> stop() async => VoiceRecording(
    bytes: Uint8List.fromList([
      ...'RIFF'.codeUnits,
      36,
      0,
      0,
      0,
      ...'WAVEfmt '.codeUnits,
      ...List<int>.filled(28, 0),
    ]),
    duration: const Duration(seconds: 2),
    fileName: 'guardian-test.wav',
  );

  @override
  Future<void> cancel() async {}

  @override
  Future<void> dispose() async {}
}
