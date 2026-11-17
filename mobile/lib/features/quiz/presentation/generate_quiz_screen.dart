import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/providers.dart';
import '../../moodle/domain/course.dart';

class GenerateQuizScreen extends ConsumerStatefulWidget {
  const GenerateQuizScreen({super.key, required this.course});

  final CourseSummary course;

  @override
  ConsumerState<GenerateQuizScreen> createState() => _GenerateQuizScreenState();
}

class _GenerateQuizScreenState extends ConsumerState<GenerateQuizScreen> {
  late final TextEditingController _title;
  int _count = 5;
  final Set<String> _types = {'MULTICHOICE', 'TRUEFALSE'};
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _title = TextEditingController(text: 'اختبار — ${widget.course.title}');
  }

  @override
  void dispose() {
    _title.dispose();
    super.dispose();
  }

  Future<void> _generate() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final session = ref.read(sessionProvider);
      final draft = await ref.read(quizRepositoryProvider).requestGeneration(
            courseId: widget.course.id,
            connectionId: session?.membershipId ?? '00000000-0000-4000-8000-000000000001',
            title: _title.text.trim(),
            questionCount: _count,
            questionTypes: _types.toList(),
          );
      if (!mounted) return;
      context.push('/tasks/${draft.taskId}/preview');
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('توليد اختبار')),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          Text('المقرر: ${widget.course.title}',
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 16),
          TextField(
            controller: _title,
            decoration: const InputDecoration(labelText: 'عنوان الاختبار'),
          ),
          const SizedBox(height: 16),
          Text('عدد الأسئلة: $_count'),
          Slider(
            value: _count.toDouble(),
            min: 1,
            max: 10,
            divisions: 9,
            label: '$_count',
            onChanged: (v) => setState(() => _count = v.round()),
          ),
          const Text('أنواع الأسئلة'),
          CheckboxListTile(
            value: _types.contains('MULTICHOICE'),
            onChanged: (v) => setState(() {
              if (v == true) {
                _types.add('MULTICHOICE');
              } else {
                _types.remove('MULTICHOICE');
              }
            }),
            title: const Text('اختيار من متعدد'),
          ),
          CheckboxListTile(
            value: _types.contains('TRUEFALSE'),
            onChanged: (v) => setState(() {
              if (v == true) {
                _types.add('TRUEFALSE');
              } else {
                _types.remove('TRUEFALSE');
              }
            }),
            title: const Text('صح / خطأ'),
          ),
          CheckboxListTile(
            value: _types.contains('SHORTANSWER'),
            onChanged: (v) => setState(() {
              if (v == true) {
                _types.add('SHORTANSWER');
              } else {
                _types.remove('SHORTANSWER');
              }
            }),
            title: const Text('إجابة قصيرة'),
          ),
          if (_error != null)
            Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          const SizedBox(height: 16),
          FilledButton(
            onPressed: _loading || _types.isEmpty ? null : _generate,
            child: _loading
                ? const SizedBox(
                    height: 22,
                    width: 22,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('توليد المسودة'),
          ),
        ],
      ),
    );
  }
}
