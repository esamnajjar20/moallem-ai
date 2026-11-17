import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/providers.dart';
import '../domain/course.dart';

class CoursesScreen extends ConsumerStatefulWidget {
  const CoursesScreen({super.key});

  @override
  ConsumerState<CoursesScreen> createState() => _CoursesScreenState();
}

class _CoursesScreenState extends ConsumerState<CoursesScreen> {
  late Future<List<CourseSummary>> _future;

  @override
  void initState() {
    super.initState();
    _future = ref.read(moodleRepositoryProvider).listCourses();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('مقرراتي'),
        actions: [
          IconButton(
            tooltip: 'ربط Moodle',
            onPressed: () => context.push('/moodle/connect'),
            icon: const Icon(Icons.link),
          ),
        ],
      ),
      body: FutureBuilder<List<CourseSummary>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return Center(child: Text('خطأ: ${snap.error}'));
          }
          final courses = snap.data ?? [];
          if (courses.isEmpty) {
            return Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Text('لا توجد مقررات. اربط حساب Moodle أولاً.'),
                  const SizedBox(height: 12),
                  FilledButton(
                    onPressed: () => context.push('/moodle/connect'),
                    child: const Text('ربط Moodle'),
                  ),
                ],
              ),
            );
          }
          return ListView.separated(
            itemCount: courses.length,
            separatorBuilder: (_, __) => const Divider(height: 1),
            itemBuilder: (context, i) {
              final c = courses[i];
              return ListTile(
                title: Text(c.title),
                subtitle: c.shortName != null ? Text(c.shortName!) : null,
                trailing: const Icon(Icons.chevron_left),
                onTap: () => context.push('/courses/${c.id}/generate', extra: c),
              );
            },
          );
        },
      ),
    );
  }
}
