import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/providers.dart';
import '../domain/quiz_models.dart';

class QuizPreviewScreen extends ConsumerStatefulWidget {
  const QuizPreviewScreen({super.key, required this.taskId});

  final String taskId;

  @override
  ConsumerState<QuizPreviewScreen> createState() => _QuizPreviewScreenState();
}

class _QuizPreviewScreenState extends ConsumerState<QuizPreviewScreen> {
  late Future<QuizDraft> _future;

  @override
  void initState() {
    super.initState();
    _future = ref.read(quizRepositoryProvider).awaitDraft(widget.taskId);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('معاينة الاختبار')),
      body: FutureBuilder<QuizDraft>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return Center(child: Text('خطأ: ${snap.error}'));
          }
          final draft = snap.data!;
          return Column(
            children: [
              if (draft.qualityIssues.isNotEmpty)
                Material(
                  color: Theme.of(context).colorScheme.secondaryContainer,
                  child: ListTile(
                    title: const Text('ملاحظات الجودة'),
                    subtitle: Text(draft.qualityIssues.map((e) => e.message).join('\n')),
                  ),
                ),
              Expanded(
                child: ListView.builder(
                  padding: const EdgeInsets.all(16),
                  itemCount: draft.questions.length,
                  itemBuilder: (context, i) {
                    final q = draft.questions[i];
                    return Card(
                      child: Padding(
                        padding: const EdgeInsets.all(12),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '${i + 1}. ${q.stem}',
                              style: Theme.of(context).textTheme.titleSmall,
                            ),
                            Text('${q.typeCode} — ${q.points} درجة'),
                            if (q.options.isNotEmpty)
                              ...q.options.map((o) => Text('• ${o.text}')),
                            if (q.correctAnswer != null)
                              Text('الإجابة: ${q.correctAnswer}'),
                            if (q.unsupported)
                              Text(
                                'غير مدعوم: ${q.unsupportedReason ?? ""}',
                                style: TextStyle(color: Theme.of(context).colorScheme.error),
                              ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
              ),
              SafeArea(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Row(
                    children: [
                      Expanded(
                        child: OutlinedButton(
                          onPressed: () => context.push('/tasks/${widget.taskId}/approval'),
                          child: const Text('الموافقة / الرفض'),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}
