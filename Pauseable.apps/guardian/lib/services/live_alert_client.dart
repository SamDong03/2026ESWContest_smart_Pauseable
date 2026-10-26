import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';

import '../models/live_app_alert.dart';
import 'app_authenticated_client.dart';

enum LiveAlertConnectionStatus { connecting, connected, reconnecting, stopped }

typedef WebSocketConnector = WebSocketChannel Function(Uri uri);

class LiveAlertClient {
  factory LiveAlertClient({
    required String apiBaseUrl,
    required String patientId,
    required String? Function() appTokenProvider,
    http.Client? httpClient,
    WebSocketConnector? webSocketConnector,
  }) {
    final apiBaseUri = Uri.parse(apiBaseUrl);
    return LiveAlertClient._internal(
      apiBaseUri,
      patientId,
      AppAuthenticatedClient(
        inner: httpClient ?? http.Client(),
        apiBaseUri: apiBaseUri,
        tokenProvider: appTokenProvider,
      ),
      webSocketConnector ?? (uri) => WebSocketChannel.connect(uri),
    );
  }

  LiveAlertClient._internal(
    this._apiBaseUri,
    this._patientId,
    this._httpClient,
    this._webSocketConnector,
  );

  final Uri _apiBaseUri;
  final String _patientId;
  final http.Client _httpClient;
  final WebSocketConnector _webSocketConnector;
  final StreamController<LiveAppAlert> _alerts =
      StreamController<LiveAppAlert>.broadcast();
  final StreamController<LiveAlertConnectionStatus> _statuses =
      StreamController<LiveAlertConnectionStatus>.broadcast();

  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _subscription;
  Timer? _reconnectTimer;
  bool _started = false;
  bool _disposed = false;
  int _reconnectAttempt = 0;

  Stream<LiveAppAlert> get alerts => _alerts.stream;
  Stream<LiveAlertConnectionStatus> get statuses => _statuses.stream;

  void start() {
    if (_started || _disposed) return;
    _started = true;
    _emitStatus(LiveAlertConnectionStatus.connecting);
    unawaited(_connect());
  }

  Future<void> _connect() async {
    if (_disposed) return;

    try {
      final websocketUri = await _requestWebSocketUri();
      if (_disposed) return;

      final channel = _webSocketConnector(websocketUri);
      _channel = channel;
      await channel.ready;
      if (_disposed) {
        await channel.sink.close();
        return;
      }

      _subscription = channel.stream.listen(
        _handleMessage,
        onError: (Object _, StackTrace _) {
          debugPrint('Live alert stream disconnected; retrying.');
          _scheduleReconnect();
        },
        onDone: _scheduleReconnect,
        cancelOnError: true,
      );
    } catch (_) {
      debugPrint('Live alert connection failed; retrying.');
      _scheduleReconnect();
    }
  }

  Future<Uri> _requestWebSocketUri() async {
    final ticketEndpoint = _apiBaseUri.resolve(
      '/api/patients/${Uri.encodeComponent(_patientId)}/alert-websocket-ticket',
    );
    final response = await _httpClient.post(ticketEndpoint);
    if (response.statusCode != 201) {
      throw StateError(
        'WebSocket ticket request failed (${response.statusCode}).',
      );
    }

    final payload = jsonDecode(response.body) as Map<String, dynamic>;
    final ticket = payload['ticket'] as String?;
    if (ticket == null || ticket.isEmpty) {
      throw const FormatException('WebSocket ticket is missing.');
    }

    return _apiBaseUri.replace(
      scheme: _apiBaseUri.scheme == 'https' ? 'wss' : 'ws',
      path: '/ws/alerts',
      queryParameters: {'patient_id': _patientId, 'ticket': ticket},
    );
  }

  void _handleMessage(dynamic rawMessage) {
    if (rawMessage is! String) return;

    try {
      final payload = jsonDecode(rawMessage) as Map<String, dynamic>;
      if (payload['type'] == 'ready') {
        _reconnectAttempt = 0;
        _emitStatus(LiveAlertConnectionStatus.connected);
        return;
      }
      if (payload['type'] != 'app_alert') return;
      final data = payload['data'] as Map<String, dynamic>;
      _alerts.add(LiveAppAlert.fromJson(data));
    } catch (_) {

    }
  }

  void _scheduleReconnect() {
    if (_disposed || _reconnectTimer?.isActive == true) return;
    unawaited(_subscription?.cancel() ?? Future<void>.value());
    _subscription = null;
    _channel = null;
    _emitStatus(LiveAlertConnectionStatus.reconnecting);

    const delays = [2, 5, 10, 30];
    final delayIndex = _reconnectAttempt < delays.length
        ? _reconnectAttempt
        : delays.length - 1;
    final delay = Duration(seconds: delays[delayIndex]);
    _reconnectAttempt++;
    _reconnectTimer = Timer(delay, () {
      _reconnectTimer = null;
      unawaited(_connect());
    });
  }

  void _emitStatus(LiveAlertConnectionStatus status) {
    if (!_disposed) _statuses.add(status);
  }

  Future<void> dispose() async {
    if (_disposed) return;
    _emitStatus(LiveAlertConnectionStatus.stopped);
    _disposed = true;
    _reconnectTimer?.cancel();
    await _subscription?.cancel();
    await _channel?.sink.close();
    _httpClient.close();
    await _alerts.close();
    await _statuses.close();
  }
}
