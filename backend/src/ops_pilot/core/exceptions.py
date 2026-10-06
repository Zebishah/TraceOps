class EmailAlreadyRegisteredError(Exception):
    pass


class OrganizationSlugAlreadyExistsError(Exception):
    pass


class RegistrationConflictError(Exception):
    pass


class UnsupportedDocumentTypeError(Exception):
    pass


class DocumentTooLargeError(Exception):
    pass


class DocumentUploadError(Exception):
    pass


class DocumentNotFoundError(Exception):
    pass


class DocumentProcessingError(Exception):
    pass


class IncidentNotFoundError(Exception):
    pass


class CustomerNotFoundError(Exception):
    pass


class ApprovalNotFoundError(Exception):
    pass


class ApprovalDecisionConflictError(Exception):
    pass


class ApprovalExecutionError(Exception):
    pass


class IncidentMemoryNotReadyError(Exception):
    pass


class IncidentMemoryInvalidIncidentError(Exception):
    pass
