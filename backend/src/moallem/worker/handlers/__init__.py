"""Worker task handlers."""

from moallem.worker.handlers.publish_quiz import TASK_TYPE_CREATE_QUIZ, PublishQuizHandler

__all__ = ["TASK_TYPE_CREATE_QUIZ", "PublishQuizHandler"]
