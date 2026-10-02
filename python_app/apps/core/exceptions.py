from rest_framework.exceptions import APIException


class ResourceConflict(APIException):
    status_code = 409
    default_code = "resource_conflict"
    default_detail = "该记录已关联分析任务，不能删除或替换其原始内容。"


class TaskQueueUnavailable(APIException):
    status_code = 503
    default_code = "task_queue_unavailable"
    default_detail = "任务队列暂不可用，请稍后重试。"
