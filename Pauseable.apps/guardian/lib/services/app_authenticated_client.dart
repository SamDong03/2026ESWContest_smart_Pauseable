import 'package:http/http.dart' as http;


class AppAuthenticatedClient extends http.BaseClient {
  factory AppAuthenticatedClient({
    required http.Client inner,
    required Uri apiBaseUri,
    required String? Function() tokenProvider,
  }) => AppAuthenticatedClient._(inner, apiBaseUri, tokenProvider);

  AppAuthenticatedClient._(this._inner, this._apiBaseUri, this._tokenProvider);

  final http.Client _inner;
  final Uri _apiBaseUri;
  final String? Function() _tokenProvider;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final token = _tokenProvider()?.trim();
    if (token == null || token.isEmpty) {
      throw StateError('App authentication is required.');
    }
    if (RegExp(r'\s').hasMatch(token)) {
      throw StateError('Invalid app authentication format.');
    }
    final uri = request.url;
    final isLoopback =
        uri.host == 'localhost' || uri.host == '127.0.0.1' || uri.host == '::1';
    if (uri.origin != _apiBaseUri.origin ||
        uri.userInfo.isNotEmpty ||
        (uri.scheme != 'https' && !(uri.scheme == 'http' && isLoopback))) {
      throw StateError('App credentials require the configured HTTPS API.');
    }

    request.followRedirects = false;
    request.headers['Authorization'] = 'Bearer $token';
    return _inner.send(request);
  }

  @override
  void close() => _inner.close();
}
