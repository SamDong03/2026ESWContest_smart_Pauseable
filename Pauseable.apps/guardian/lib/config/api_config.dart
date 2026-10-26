import 'package:flutter/foundation.dart' show kIsWeb;

abstract final class ApiConfig {

  static const patientId = String.fromEnvironment(
    'PATIENT_ID',
    defaultValue: 'byunwoojin',
  );

  static const baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: kIsWeb
        ? 'http://127.0.0.1:8000'
        : 'https://pauseable-api.onrender.com',
  );


  static const appToken = String.fromEnvironment('APP_TOKEN');
}
