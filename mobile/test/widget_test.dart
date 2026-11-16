import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:moallem_mobile/app.dart';
import 'package:moallem_mobile/core/app_config.dart';
import 'package:moallem_mobile/core/providers.dart';

void main() {
  testWidgets('shell renders in Arabic and lays out right-to-left',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          appConfigProvider.overrideWithValue(
            AppConfig.parse('https://api.example.invalid/api/v1'),
          ),
        ],
        child: const MoallemApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('app-title')), findsOneWidget);
    final dir = Directionality.of(tester.element(find.byKey(const Key('app-title'))));
    expect(dir, TextDirection.rtl);
  });
}
