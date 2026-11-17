import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/providers.dart';
import '../domain/quiz_models.dart';

class PublishStatusScreen extends ConsumerStatefulWidget {
  const PublishStatusScreen({super.key, required this.taskId});

  final String taskId;

  @override
  ConsumerState<PublishStatusScreen> createState() => _PublishStatusScreenState();
}

class _PublishStatusScreenState extends ConsumerState<PublishStatusScreen> {
  PublishStatus? _status;
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _run();
  }

  Future<void> _run() async {
    try {
      final repo = ref.read(quizRepositoryProvider);
      final status = await repo.getVerifiedResult(widget.taskId);
      setState(() {
        _status = status;
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('حالة النشر')),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  if (_error != null)
                    Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                  if (_status != null) ...[
                    Text('الحالة: ${_status!.state}',
                        style: Theme.of(context).textTheme.titleLarge),
                    if (_status!.moodleQuizId != null)
                      Text('معرّف الاختبار في Moodle: ${_status!.moodleQuizId}'),
                    if (_status!.message != null) Text(_status!.message!),
                  ],
                  const Spacer(),
                  FilledButton(
                    onPressed: () => context.go('/courses'),
                    child: const Text('العودة للمقررات'),
                  ),
                ],
              ),
      ),
    );
  }
}
