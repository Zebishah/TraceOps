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
