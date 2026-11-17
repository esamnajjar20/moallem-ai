import 'dart:convert';

import 'package:http/http.dart' as http;

import '../app_config.dart';
import 'api_exception.dart';

/// Thin HTTP client for Moallem API v1.
/// Attaches Bearer token and X-Active-Membership-ID when present.
class ApiClient {
  ApiClient({
    required this.config,
    http.Client? httpClient,
  }) : _http = httpClient ?? http.Client();

  final AppConfig config;
  final http.Client _http;

  String? accessToken;
  String? activeMembershipId;

  Uri _uri(String path, [Map<String, String>? query]) {
    final base = config.apiBaseUrl;
    final normalized = path.startsWith('/') ? path.substring(1) : path;
    final joined = base.path.endsWith('/')
        ? '${base.path}$normalized'
        : '${base.path}/$normalized';
    return base.replace(path: joined, queryParameters: query);
  }

  Map<String, String> _headers() {
    final h = <String, String>{
      'Accept': 'application/json',
      'Content-Type': 'application/json',
    };
    if (accessToken != null && accessToken!.isNotEmpty) {
      h['Authorization'] = 'Bearer $accessToken';
    }
    if (activeMembershipId != null && activeMembershipId!.isNotEmpty) {
      h['X-Active-Membership-ID'] = activeMembershipId!;
    }
    return h;
  }

  Future<Map<String, dynamic>> getJson(String path, {Map<String, String>? query}) async {
    final res = await _http.get(_uri(path, query), headers: _headers());
    return _decode(res);
  }

  Future<Map<String, dynamic>> postJson(String path, {Object? body, Map<String, String>? headers}) async {
    final h = _headers();
    if (headers != null) h.addAll(headers);
    final res = await _http.post(
      _uri(path),
      headers: h,
      body: body == null ? null : jsonEncode(body),
    );
    return _decode(res);
  }

  Map<String, dynamic> _decode(http.Response res) {
    Map<String, dynamic>? payload;
    if (res.body.isNotEmpty) {
      try {
        final decoded = jsonDecode(res.body);
        if (decoded is Map<String, dynamic>) payload = decoded;
      } catch (_) {
        /* non-json */
      }
    }
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return payload ?? <String, dynamic>{};
    }
    final err = payload?['error'];
    final message = err is Map
        ? (err['message']?.toString() ?? 'request failed')
        : (payload?['message']?.toString() ?? 'request failed');
    final code = err is Map ? err['code']?.toString() : null;
    throw ApiException(message: message, statusCode: res.statusCode, code: code);
  }

  void close() => _http.close();
}
