import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app_config.dart';

/// Must be overridden in main() (and in tests); reading it unoverridden is a bug.
final appConfigProvider = Provider<AppConfig>(
  (ref) => throw UnimplementedError('appConfigProvider must be overridden'),
);
