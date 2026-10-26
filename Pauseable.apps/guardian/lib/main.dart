import 'package:flutter/material.dart';

import 'app.dart';
import 'config/api_config.dart';
import 'repositories/api_guardian_repository.dart';
import 'services/live_alert_client.dart';
import 'services/native_push_client.dart';
import 'services/web_push_client.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  String tokenProvider() => ApiConfig.appToken;
  runApp(
    PauseableApp(
      repository: ApiGuardianRepository(
        baseUrl: ApiConfig.baseUrl,
        patientId: ApiConfig.patientId,
        appTokenProvider: tokenProvider,
      ),
      liveAlertClient: LiveAlertClient(
        apiBaseUrl: ApiConfig.baseUrl,
        patientId: ApiConfig.patientId,
        appTokenProvider: tokenProvider,
      ),
      webPushClient: WebPushClient(
        baseUrl: ApiConfig.baseUrl,
        patientId: ApiConfig.patientId,
        appTokenProvider: tokenProvider,
      ),
      nativePushClient: NativePushClient(
        baseUrl: ApiConfig.baseUrl,
        patientId: ApiConfig.patientId,
        appTokenProvider: tokenProvider,
      ),
    ),
  );
}
