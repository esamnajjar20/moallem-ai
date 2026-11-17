import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:moallem_mobile/app.dart';
import 'package:moallem_mobile/core/app_config.dart';
import 'package:moallem_mobile/core/providers.dart';

void main() {
  testWidgets('login screen renders in mock mode', (tester) async {
    final config = AppConfig.parse('', useMocks: true);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [appConfigProvider.overrideWithValue(config)],
        child: const MoallemApp(),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('معلم AI'), findsOneWidget);
    expect(find.text('دخول'), findsOneWidget);
  });
}
