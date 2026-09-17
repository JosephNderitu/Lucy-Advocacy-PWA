# --- Append to core/forms.py ---
from django import forms
from .models import CaseDocument, Review, Case

INPUT_CLS = (
    "w-full rounded-lg border border-gray-300 px-4 py-3 text-sm "
    "focus:outline-none focus:ring-2 focus:ring-brand-teal-500 focus:border-transparent"
)

MAX_UPLOAD_MB = 75


class ClientLoginForm(forms.Form):
    case_number = forms.CharField(
        label="Case number",
        widget=forms.TextInput(attrs={"class": INPUT_CLS, "placeholder": "e.g. NWC-2026-014", "autofocus": True}),
    )
    id_no = forms.CharField(
        label="ID number",
        widget=forms.TextInput(attrs={"class": INPUT_CLS, "placeholder": "National ID number"}),
    )


class DocumentUploadForm(forms.ModelForm):
    class Meta:
        model = CaseDocument
        fields = ["file"]
        widgets = {
            "file": forms.ClearableFileInput(attrs={
                "class": INPUT_CLS,
                "accept": ".pdf,.doc,.docx,.jpg,.jpeg,.png,.mp4,.mov",
            }),
        }

    def clean_file(self):
        f = self.cleaned_data["file"]
        ext = "." + f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
        if ext not in CaseDocument.ALLOWED_EXTENSIONS:
            raise forms.ValidationError(
                "Unsupported file type. Allowed: PDF, Word (.doc/.docx), images (.jpg/.png), video (.mp4/.mov)."
            )
        if f.size > MAX_UPLOAD_MB * 1024 * 1024:
            raise forms.ValidationError(f"File is too large. Maximum size is {MAX_UPLOAD_MB}MB.")
        return f
    

class CaseAdminForm(forms.ModelForm):
    """Used only in the admin. On a new Case, these three extra fields create
    the User + ClientProfile behind the scenes (see CaseAdmin.save_model) —
    the admin never touches Users or Client profiles directly."""

    client_full_name = forms.CharField(label="Client full name", required=False)
    client_id_no = forms.CharField(
        label="Client ID number", required=False,
        help_text="This becomes part of the client's portal login.",
    )
    client_phone = forms.CharField(label="Client phone (optional)", required=False)

    class Meta:
        model = Case
        fields = ["case_number", "title", "status"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            # Editing an existing case — client is already linked, hide the
            # creation-only fields rather than showing them empty.
            for name in ("client_full_name", "client_id_no", "client_phone"):
                self.fields[name].widget = forms.HiddenInput()
        else:
            self.fields["client_full_name"].required = True
            self.fields["client_id_no"].required = True

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk:
            if not cleaned.get("client_full_name", "").strip():
                self.add_error("client_full_name", "Required for a new case.")
            if not cleaned.get("client_id_no", "").strip():
                self.add_error("client_id_no", "Required for a new case.")
        return cleaned
    

class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ["name", "message", "rating"]

    def clean_name(self):
        return self.cleaned_data["name"].strip()

    def clean_message(self):
        return self.cleaned_data["message"].strip()

    def clean_rating(self):
        rating = self.cleaned_data["rating"]
        if rating not in (1, 2, 3, 4, 5):
            raise forms.ValidationError("Rating must be between 1 and 5.")
        return rating