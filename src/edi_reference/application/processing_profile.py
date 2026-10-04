"""Resolve tenant/application processing profiles deterministically."""

from edi_reference.domain.processing_profile import ProcessingProfile, ProcessingProfileBinding


class ProcessingProfileError(ValueError):
    pass


class ProcessingProfileRegistry:
    def __init__(
        self,
        profiles: tuple[ProcessingProfile, ...],
        bindings: tuple[ProcessingProfileBinding, ...],
    ):
        self._profiles: dict[tuple[str, str], ProcessingProfile] = {}
        for profile in profiles:
            key = (profile.profile_id, profile.profile_version)
            if key in self._profiles:
                raise ProcessingProfileError("DUPLICATE_PROCESSING_PROFILE")
            self._profiles[key] = profile

        self._bindings: dict[tuple[str, str | None], ProcessingProfileBinding] = {}
        for binding in bindings:
            binding_key = (binding.tenant_id, binding.application_id)
            if binding_key in self._bindings:
                raise ProcessingProfileError("DUPLICATE_PROCESSING_PROFILE_BINDING")
            if (binding.profile_id, binding.profile_version) not in self._profiles:
                raise ProcessingProfileError("PROCESSING_PROFILE_NOT_FOUND")
            self._bindings[binding_key] = binding

    def resolve(self, *, tenant_id: str, application_id: str) -> ProcessingProfile:
        binding = self._bindings.get((tenant_id, application_id))
        if binding is None:
            binding = self._bindings.get((tenant_id, None))
        if binding is None:
            raise ProcessingProfileError("PROCESSING_PROFILE_NOT_BOUND")

        return self._profiles[(binding.profile_id, binding.profile_version)]
