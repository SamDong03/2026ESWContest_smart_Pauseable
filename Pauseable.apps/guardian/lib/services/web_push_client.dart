import 'dart:convert';

import 'package:http/http.dart' as http;

import 'app_authenticated_client.dart';
import 'web_push_browser.dart';
import 'web_push_browser_interface.dart';

class WebPushState {
  const WebPushState({
    required this.browserSupported,
    required this.serverEnabled,
    required this.permission,
    required this.subscribed,
    this.publicKey,
  });

  final bool browserSupported;
  final bool serverEnabled;
  final String permission;
  final bool subscribed;
  final String? publicKey;
}

class WebPushClient {
  WebPushClient({
    required String baseUrl,
    required this.patientId,
    required String? Function() appTokenProvider,
    http.Client? httpClient,
    WebPushBrowser? browser,
  }) : _baseUri = Uri.parse(baseUrl),
       _browser = browser ?? createWebPushBrowser(),
       _client = AppAuthenticatedClient(
         inner: httpClient ?? http.Client(),
         apiBaseUri: Uri.parse(baseUrl),
         tokenProvider: appTokenProvider,
       );

  final Uri _baseUri;
  final String patientId;
  final WebPushBrowser _browser;
  final http.Client _client;

  Uri _uri(String suffix) => _baseUri.resolve(
    '/api/patients/${Uri.encodeComponent(patientId)}/push/$suffix',
  );

  Future<WebPushState> loadState() async {
    if (!_browser.isSupported) {
      return const WebPushState(
        browserSupported: false,
        serverEnabled: false,
        permission: 'unsupported',
        subscribed: false,
      );
    }
    final response = await _client
        .get(_uri('config'))
        .timeout(const Duration(seconds: 8));
    if (response.statusCode != 200) {
      throw StateError(
        'Push configuration request failed (${response.statusCode}).',
      );
    }
    final config = jsonDecode(response.body) as Map<String, dynamic>;
    final enabled = config['enabled'] == true;
    final subscription = await _browser.currentSubscription();
    if (enabled && subscription != null) {

      await _register(subscription);
    }
    return WebPushState(
      browserSupported: true,
      serverEnabled: enabled,
      permission: _browser.permission,
      subscribed: subscription != null,
      publicKey: config['public_key'] as String?,
    );
  }

  Future<void> enable(String publicKey) async {

    final subscription = await _browser.subscribe(publicKey);
    try {
      await _register(subscription);
    } catch (_) {
      await _browser.unsubscribe();
      rethrow;
    }
  }

  Future<void> disable() async {
    final subscription = await _browser.currentSubscription();
    if (subscription == null) return;
    final parsed = jsonDecode(subscription) as Map<String, dynamic>;
    final endpoint = parsed['endpoint'] as String;
    final response = await _client
        .delete(
          _uri('subscriptions'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({'endpoint': endpoint}),
        )
        .timeout(const Duration(seconds: 8));
    if (response.statusCode != 204) {
      throw StateError(
        'Push unsubscribe request failed (${response.statusCode}).',
      );
    }
    if (!await _browser.unsubscribe()) {
      throw StateError('Browser push subscription could not be removed.');
    }
  }

  Future<String> scheduleTest() async {
    final subscription = await _browser.currentSubscription();
    if (subscription == null) {
      throw StateError('This browser is not subscribed.');
    }
    final parsed = jsonDecode(subscription) as Map<String, dynamic>;
    final response = await _client
        .post(
          _uri('test'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({
            'endpoint': parsed['endpoint'],
            'delay_seconds': 10,
          }),
        )
        .timeout(const Duration(seconds: 30));
    if (response.statusCode != 202) {
      throw StateError(
        'Push test could not be scheduled (${response.statusCode}).',
      );
    }
    final result = jsonDecode(response.body) as Map<String, dynamic>;
    return result['test_id'] as String;
  }

  Future<String> testResult(String testId) async {
    final response = await _client
        .get(_uri('test/${Uri.encodeComponent(testId)}'))
        .timeout(const Duration(seconds: 30));
    if (response.statusCode != 200) {
      throw StateError('Push test result is unavailable.');
    }
    final result = jsonDecode(response.body) as Map<String, dynamic>;
    return result['status'] as String;
  }

  Future<void> _register(String subscriptionJson) async {
    final subscription = jsonDecode(subscriptionJson) as Map<String, dynamic>;
    final response = await _client
        .post(
          _uri('subscriptions'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode(subscription),
        )
        .timeout(const Duration(seconds: 8));
    if (response.statusCode != 201) {
      throw StateError(
        'Push subscription request failed (${response.statusCode}).',
      );
    }
  }

  void dispose() => _client.close();
}
