import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/providers.dart';

class ApprovalScreen extends ConsumerStatefulWidget {
  const ApprovalScreen({super.key, required this.taskId});

  final String taskId;

  @override
  ConsumerState<ApprovalScreen> createState() => _ApprovalScreenState();
}

class _ApprovalScreenState extends ConsumerState<ApprovalScreen> {
  bool _loading = false;
  String? _error;

  Future<void> _decide(bool approve) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final repo = ref.read(quizRepositoryProvider);
      // Snapshot ids come from GET /tasks/{id}/snapshot in API mode.
      // Mocks accept any non-empty values.
      const snapshotId = '00000000-0000-4000-8000-0000000000s1';
      const snapshotHash = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef';
      if (approve) {
        await repo.approve(widget.taskId, snapshotId: snapshotId, snapshotHash: snapshotHash);
        if (!mounted) return;
        context.push('/tasks/${widget.taskId}/publish');
      } else {
        await repo.reject(
          widget.taskId,
          snapshotId: snapshotId,
          snapshotHash: snapshotHash,
          reason: 'رفض المعلم',
        );
        if (!mounted) return;
        context.go('/courses');
      }
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('الموافقة على النشر')),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'بالموافقة سيتم تجهيز الاختبار للنشر إلى Moodle. '
              'يمكنك الرفض لإعادة التوليد لاحقاً.',
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ],
            const Spacer(),
            FilledButton(
              onPressed: _loading ? null : () => _decide(true),
              child: const Text('موافقة ونشر'),
            ),
            const SizedBox(height: 8),
            OutlinedButton(
              onPressed: _loading ? null : () => _decide(false),
              child: const Text('رفض المسودة'),
            ),
          ],
        ),
      ),
    );
  }
}
