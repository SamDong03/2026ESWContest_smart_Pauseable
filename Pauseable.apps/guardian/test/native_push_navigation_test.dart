import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:pauseable_guardian/app.dart';
import 'package:pauseable_guardian/models/guardian_snapshot.dart';
import 'package:pauseable_guardian/models/home_environment.dart';
import 'package:pauseable_guardian/models/live_app_alert.dart';
import 'package:pauseable_guardian/repositories/mock_guardian_repository.dart';
import 'package:pauseable_guardian/services/home_region_catalog.dart';
import 'package:pauseable_guardian/services/native_push_client.dart';
import 'package:pauseable_guardian/services/native_push_platform_interface.dart';
import 'package:pauseable_guardian/services/voice_training_script_loader.dart';

class _LaunchPlatform implements NativePushPlatform {
  bool initialOpen = true;
  @override
  bool get isSupported => true;
  @override
  Stream<String> get tokenRefreshes => const Stream.empty();
  @override
  Stream<void> get notificationOpens => const Stream.empty();
  @override
  Future<void> initialize(String patientId) async {}
  @override
  Future<NativePushPermission> permission({required bool request}) async =>
      NativePushPermission.granted;
  @override
  Future<String?> token() async => 'private-test-device-token';
  @override
  bool consumeInitialNotificationOpen() {
    final value = initialOpen;
    initialOpen = false;
    return value;
  }

  @override
  Future<void> openNotificationSettings() async {}
  @override
  Future<void> dispose() async {}
}

class _LoadingHomeRepository extends MockGuardianRepository {
  _LoadingHomeRepository(this.snapshot);
  final GuardianSnapshot snapshot;
  final loadingHome = Completer<HomeEnvironment>();
  int historyLoads = 0;
  @override
  Future<GuardianSnapshot> loadSnapshot() async => snapshot;
  @override
  Future<HomeEnvironment> loadHomeEnvironment() => loadingHome.future;
  @override
  Future<List<LiveAppAlert>> loadAlertHistory() async {
    historyLoads++;
    return const [];
  }
}

void main() {
  late GuardianSnapshot snapshot;
  setUpAll(() async {
    snapshot = await MockGuardianRepository().loadSnapshot();
    await HomeRegionCatalog.load();
    await VoiceTrainingScriptLoader.load();
  });

  for (final cachedHome in [false, true]) {
    testWidgets('cold notification opens alerts with home cached=$cachedHome', (
      tester,
    ) async {
      final repository = _LoadingHomeRepository(snapshot);
      if (cachedHome) {
        repository.loadingHome.complete(
          HomeEnvironment(region: (await HomeRegionCatalog.load()).first),
        );
      }
      final client = NativePushClient(
        baseUrl: 'https://api.example.test',
        patientId: 'byunwoojin',
        appTokenProvider: () => 'test-app-token',
        platform: _LaunchPlatform(),
        httpClient: MockClient(
          (request) async => http.Response(
            request.method == 'GET'
                ? '{"configured":true}'
                : '{"registered":true}',
            request.method == 'GET' ? 200 : 201,
          ),
        ),
      );
      await tester.pumpWidget(
        PauseableApp(repository: repository, nativePushClient: client),
      );
      await tester.pumpAndSettle();
      expect(repository.loadingHome.isCompleted, cachedHome);
      expect(
        tester.widget<NavigationBar>(find.byType(NavigationBar)).selectedIndex,
        1,
      );
      expect(find.text('거주 지역 설정'), findsNothing);
      expect(find.byType(CircularProgressIndicator), findsNothing);
      expect(repository.historyLoads, greaterThanOrEqualTo(1));

      if (!cachedHome) repository.loadingHome.complete(const HomeEnvironment());
      await tester.pumpAndSettle();
      expect(
        tester.widget<NavigationBar>(find.byType(NavigationBar)).selectedIndex,
        1,
      );
    });
  }
}
