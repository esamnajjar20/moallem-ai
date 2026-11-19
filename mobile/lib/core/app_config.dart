/// Build-time configuration.
///
///   flutter run --dart-define=MOALLEM_API_BASE_URL=https://api.example.com/api/v1 \
///               --dart-define=MOALLEM_USE_MOCKS=true \
///               --dart-define=MOALLEM_CONNECTION_ID=<moodle connection uuid>
///
/// No secrets belong here.
class AppConfig {
  const AppConfig({
    required this.apiBaseUrl,
    this.useMocks = false,
    this.connectionId,
  });

  final Uri apiBaseUrl;
  final bool useMocks;

  /// Moodle connection UUID used until the connection-management API exists (CONN-API).
  final String? connectionId;

  static const String _rawBaseUrl = String.fromEnvironment('MOALLEM_API_BASE_URL');
  static const String _rawUseMocks = String.fromEnvironment(
    'MOALLEM_USE_MOCKS',
    defaultValue: 'false',
  );

  static const String _rawConnectionId = String.fromEnvironment('MOALLEM_CONNECTION_ID');

  factory AppConfig.fromEnvironment() => AppConfig.parse(
        _rawBaseUrl,
        useMocks: _rawUseMocks.toLowerCase() == 'true',
        connectionId: _rawConnectionId.isEmpty ? null : _rawConnectionId,
      );

  factory AppConfig.parse(String raw, {bool useMocks = false, String? connectionId}) {
    if (useMocks && raw.isEmpty) {
      return AppConfig(
        apiBaseUrl: Uri.parse('https://mock.local/api/v1'),
        useMocks: true,
      );
    }
    final uri = Uri.tryParse(raw);
    if (raw.isEmpty ||
        uri == null ||
        !uri.hasAuthority ||
        !(uri.scheme == 'https' || uri.scheme == 'http')) {
      throw StateError(
        'MOALLEM_API_BASE_URL must be an absolute http(s) URL '
        '(pass --dart-define=MOALLEM_API_BASE_URL=...), '
        'or set MOALLEM_USE_MOCKS=true for local UI work.',
      );
    }
    return AppConfig(apiBaseUrl: uri, useMocks: useMocks, connectionId: connectionId);
  }
}
