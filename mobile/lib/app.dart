import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

/// Root widget. Arabic (RTL) is the primary locale; English is the fallback.
/// Screens arrive in P8; P1 only proves the shell builds, themes, and lays out RTL.
class MoallemApp extends StatelessWidget {
  const MoallemApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Moallem AI',
      locale: const Locale('ar'),
      supportedLocales: const [Locale('ar'), Locale('en')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      theme: ThemeData(useMaterial3: true, colorSchemeSeed: Colors.indigo),
      home: const Scaffold(
        body: Center(child: Text('معلم AI', key: Key('app-title'))),
      ),
    );
  }
}
