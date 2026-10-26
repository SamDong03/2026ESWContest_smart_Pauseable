import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pauseable_guardian/screens/voice_recording_consent_sheet.dart';
import 'package:pauseable_guardian/repositories/mock_guardian_repository.dart';

void main() {
  for (final mode in [ThemeMode.light, ThemeMode.dark]) {
    testWidgets('voice policy is readable on a phone in $mode', (tester) async {
      tester.view.physicalSize = const Size(360, 640);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        MaterialApp(
          theme: ThemeData(colorSchemeSeed: Colors.green),
          darkTheme: ThemeData(
            colorSchemeSeed: Colors.green,
            brightness: Brightness.dark,
          ),
          themeMode: mode,
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context)
                .copyWith(textScaler: const TextScaler.linear(1.3)),
            child: child!,
          ),
          home: Scaffold(
            body: VoiceRecordingConsentSheet(
              repository: MockGuardianRepository(),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('보호자 음성 수집·이용 동의'), findsOneWidget);
      expect(find.textContaining('24시간'), findsOneWidget);
      expect(find.textContaining('학습 세트 생성 후 14일'), findsOneWidget);
      expect(find.textContaining('복구를 위한 7일'), findsOneWidget);
      expect(find.textContaining('Cloudflare R2'), findsOneWidget);
      expect(find.textContaining('기존 알림 수신, 출입 사진 확인'), findsOneWidget);
      final next = find.byKey(const ValueKey('voice-consent-continue'));
      expect(tester.widget<FilledButton>(next).onPressed, isNull);
      final checkbox = find.byKey(const ValueKey('voice-consent-checkbox'));
      await tester.ensureVisible(checkbox);
      await tester.pumpAndSettle();
      await tester.tap(checkbox);
      await tester.pumpAndSettle();
      expect(tester.widget<FilledButton>(next).onPressed, isNotNull);
      await tester.tap(checkbox);
      await tester.pumpAndSettle();
      expect(tester.widget<FilledButton>(next).onPressed, isNull);
      await tester.ensureVisible(
        find.byKey(const ValueKey('voice-consent-decline')),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });
  }
}
