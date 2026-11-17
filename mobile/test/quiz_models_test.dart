import 'package:flutter_test/flutter_test.dart';
import 'package:moallem_mobile/features/quiz/domain/quiz_models.dart';

void main() {
  test('QuestionPreview.fromJson', () {
    final q = QuestionPreview.fromJson({
      'question_id': '1',
      'question_type_code': 'MULTICHOICE',
      'stem': 'سؤال؟',
      'points': 2,
      'options': [
        {'option_id': 'a', 'text': 'أ'},
        {'option_id': 'b', 'text': 'ب'},
      ],
      'correct_answer_preview': 'أ',
    });
    expect(q.stem, 'سؤال؟');
    expect(q.options.length, 2);
    expect(q.correctAnswer, 'أ');
  });
}
