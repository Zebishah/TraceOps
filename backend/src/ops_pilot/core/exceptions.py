class EmailAlreadyRegisteredError(Exception):
    pass


class OrganizationSlugAlreadyExistsError(Exception):
    pass


class RegistrationConflictError(Exception):
    pass
