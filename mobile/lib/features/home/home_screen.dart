import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/providers.dart';

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('معلم AI'),
        actions: [
          IconButton(
            tooltip: 'خروج',
            onPressed: () async {
              await ref.read(authRepositoryProvider).logout();
              ref.read(sessionProvider.notifier).state = null;
              if (context.mounted) context.go('/login');
            },
            icon: const Icon(Icons.logout),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          Text(
            'مرحباً ${session?.displayName ?? ""}',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 8),
          Text(
            session?.moodleConnected == true
                ? 'حساب Moodle مرتبط'
                : 'لم يتم ربط Moodle بعد',
          ),
          const SizedBox(height: 24),
          Card(
            child: ListTile(
              leading: const Icon(Icons.link),
              title: const Text('ربط / إدارة Moodle'),
              onTap: () => context.push('/moodle/connect'),
            ),
          ),
          Card(
            child: ListTile(
              leading: const Icon(Icons.menu_book),
              title: const Text('المقررات وتوليد الاختبارات'),
              onTap: () => context.push('/courses'),
            ),
          ),
        ],
      ),
    );
  }
}
