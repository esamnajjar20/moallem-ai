/// Build-time configuration, supplied with:
///   flutter run --dart-define=MOALLEM_API_BASE_URL=https://api.example.invalid/api/v1
///
/// No secrets belong here: anything compiled into the app is extractable.
class AppConfig {
  const AppConfig({required this.apiBaseUrl});

  final Uri apiBaseUrl;

  static const String _rawBaseUrl = String.fromEnvironment(
    'MOALLEM_API_BASE_URL',
  );

  /// Fails fast: throws [StateError] on a missing or malformed base URL.
  factory AppConfig.fromEnvironment() => AppConfig.parse(_rawBaseUrl);

  factory AppConfig.parse(String raw) {
    final uri = Uri.tryParse(raw);
    if (raw.isEmpty ||
        uri == null ||
        !uri.hasAuthority ||
        !(uri.scheme == 'https' || uri.scheme == 'http')) {
      throw StateError(
        'MOALLEM_API_BASE_URL must be an absolute http(s) URL '
        '(pass --dart-define=MOALLEM_API_BASE_URL=...).',
      );
    }
    return AppConfig(apiBaseUrl: uri);
  }
}
