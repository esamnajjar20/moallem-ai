import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/providers.dart';

class ConnectMoodleScreen extends ConsumerStatefulWidget {
  const ConnectMoodleScreen({super.key});

  @override
  ConsumerState<ConnectMoodleScreen> createState() => _ConnectMoodleScreenState();
}

class _ConnectMoodleScreenState extends ConsumerState<ConnectMoodleScreen> {
  final _url = TextEditingController(text: 'https://moodle.staging.example');
  final _token = TextEditingController();
  bool _loading = false;
  String? _error;

  @override
  void dispose() {
    _url.dispose();
    _token.dispose();
    super.dispose();
  }

  Future<void> _connect() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final repo = ref.read(moodleRepositoryProvider);
      final status = await repo.connect(
        siteUrl: _url.text.trim(),
        token: _token.text.trim(),
      );
      final session = ref.read(sessionProvider);
      if (session != null) {
        ref.read(sessionProvider.notifier).state =
            session.copyWith(moodleConnected: status.connected);
      }
      if (!mounted) return;
      context.go('/courses');
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('ربط حساب Moodle')),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          const Text(
            'أدخل رابط موقع Moodle ورمز خدمة الويب الخاص بالمعلم.',
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _url,
            decoration: const InputDecoration(labelText: 'رابط الموقع (HTTPS)'),
            textDirection: TextDirection.ltr,
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _token,
            decoration: const InputDecoration(labelText: 'Web Service Token'),
            obscureText: true,
            textDirection: TextDirection.ltr,
          ),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
          const SizedBox(height: 24),
          FilledButton(
            onPressed: _loading ? null : _connect,
            child: _loading
                ? const SizedBox(
                    height: 22,
                    width: 22,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('ربط الحساب'),
          ),
        ],
      ),
    );
  }
}
