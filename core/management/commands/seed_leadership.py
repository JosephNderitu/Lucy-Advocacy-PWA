from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand

from core.models import TeamMember

LEADERS = [
    {
        "slug": "lucy-ngima-wangai",
        "name": "Lucy Ngima Wangai",
        "role": "Managing Partner",
        "order": 1,
        "email": "nwangailawadvocates@gmail.com",
        "credentials": "LLB, University of Nairobi | PG Diploma, Kenya School of Law | Law Society of Kenya | Certified Mediator",
        "bio": (
            "Ms. Wangai holds a Bachelor of Laws (LLB) degree from the University of Nairobi "
            "and a Postgraduate Diploma in Law from the Kenya School of Law. She is a member "
            "of the Law Society of Kenya and a certified professional mediator.\n\n"
            "She leads the firm's litigation and dispute resolution practice, and is an "
            "excellent litigator with remarkable legal advocacy skills. She has handled "
            "several high-profile cases in the High Court, Court of Appeal, and the "
            "Supreme Court.\n\n"
            "She is also involved in the firm's commercial, property, and conveyancing law "
            "practice, with focus areas spanning banking securities, financial services law, "
            "property conveyance law, and corporate law, and has considerable experience "
            "advising limited companies on risk management, legal audit, tax law, and "
            "contract law."
        ),
    },
    {
        "slug": "william-kathuku-mutua",
        "name": "William Kathuku Mutua",
        "role": "Partner",
        "order": 2,
        "email": "nwangailawadvocates@gmail.com",
        "credentials": "Law Degree, University of Nairobi | PG Diploma, Kenya School of Law | Law Society of Kenya",
        "bio": (
            "Mr. Mutua is a Partner in the firm. He holds a law degree from the University "
            "of Nairobi and a Postgraduate Diploma from the Kenya School of Law, and is a "
            "member of the Law Society of Kenya.\n\n"
            "He has experience providing legal services to corporates, including banks and "
            "co-operative societies, giving him deep insight into the dynamics of the "
            "corporate world, and has guided companies on their investments and compliance "
            "requirements.\n\n"
            "His focus is on commercial and corporate law litigation practice. He also "
            "supports the firm's corporate clients in navigating the increasingly "
            "challenging environment of employment and labour relations, through advisory "
            "support, advocacy, and legal representation."
        ),
    },
]


def find_existing_photo(slug):
    """Look for static/images/profiles/<slug>.jpg so photos needn't be re-uploaded."""
    roots = [Path(settings.BASE_DIR) / "static"]
    roots += [Path(p) for p in getattr(settings, "STATICFILES_DIRS", [])]
    for root in roots:
        candidate = root / "images" / "profiles" / f"{slug}.jpg"
        if candidate.exists():
            return candidate
    return None


class Command(BaseCommand):
    help = "Create the two leadership profiles (safe to re-run: never overwrites admin edits)."

    def handle(self, *args, **options):
        for data in LEADERS:
            slug = data["slug"]
            member, created = TeamMember.objects.get_or_create(
                slug=slug, defaults={**data, "is_leadership": True, "is_active": True}
            )
            self.stdout.write(f"{'Created' if created else 'Exists '}: {member.name}")
            if not member.photo:
                src = find_existing_photo(slug)
                if src:
                    with src.open("rb") as fh:
                        member.photo.save(f"{slug}.jpg", File(fh), save=True)
                    self.stdout.write(f"  attached photo from {src}")
                else:
                    self.stdout.write("  no photo found - upload one in the admin")
