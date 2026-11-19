import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'core/app_config.dart';
import 'core/providers.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final config = AppConfig.fromEnvironment();
  final container = ProviderContainer(
    overrides: [appConfigProvider.overrideWithValue(config)],
  );
  // Restore a previously validated token (secure storage) before the router starts.
  final restored = await container.read(authRepositoryProvider).restoreSession();
  container.read(sessionProvider.notifier).state = restored;
  runApp(UncontrolledProviderScope(container: container, child: const MoallemApp()));
}
