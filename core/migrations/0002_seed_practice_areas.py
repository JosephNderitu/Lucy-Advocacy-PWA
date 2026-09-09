from django.db import migrations

PRACTICE_AREAS = [
    {
        "order": 1,
        "title": "Banking & Financial Institutions",
        "icon_class": "fa-solid fa-building-columns",
        "description": (
            "We advise on local and international banking laws, lending, securities "
            "documentation, and compliance. Our team facilitates loan structuring, "
            "registration of securities, and bank-customer regulatory matters. We also "
            "represent clients in debt recovery and banking-related litigation at all "
            "levels of the judiciary, ensuring secure and compliant financial "
            "transactions for all stakeholders."
        ),
    },
    {
        "order": 2,
        "title": "Alternative Dispute Resolution",
        "icon_class": "fa-solid fa-handshake",
        "description": (
            "We offer practical dispute resolution through negotiation, mediation, "
            "arbitration, and litigation. Our lawyers handle civil and commercial "
            "disputes, labor and employment matters, tribunal representation, and "
            "international arbitration. We prioritize efficient, cost-effective "
            "outcomes while protecting our clients' interests and preserving business "
            "relationships, no matter the complexity of the dispute involved."
        ),
    },
    {
        "order": 3,
        "title": "Immigration & Private International Law",
        "icon_class": "fa-solid fa-earth-africa",
        "description": (
            "We offer guidance on immigration and cross-border legal matters, helping "
            "individuals and organizations navigate private international law issues. "
            "Our services include legal support for residency applications, work "
            "permits, citizenship, international family law, and multi-jurisdictional "
            "legal conflicts. We ensure that clients remain compliant with relevant "
            "laws in every applicable jurisdiction."
        ),
    },
    {
        "order": 4,
        "title": "Conveyancing & Real Estate Law",
        "icon_class": "fa-solid fa-house-chimney",
        "description": (
            "We handle a wide range of property matters including transfers, leases, "
            "and registration. Our services cover property transactions, charges, "
            "debentures, loan agreements, sectional property dealings, and long-term "
            "leases. We work with banks, developers, and individuals to ensure secure, "
            "efficient, and legally sound property transactions at all stages of "
            "ownership."
        ),
    },
    {
        "order": 5,
        "title": "Insurance Law",
        "icon_class": "fa-solid fa-umbrella",
        "description": (
            "Our firm represents insurers and insured parties in all types of "
            "insurance litigation. We handle motor vehicle claims, bad faith disputes, "
            "and out-of-court settlements. With a strong understanding of insurance "
            "law, we deliver fair, timely, and effective representation that protects "
            "client interests and helps manage legal and financial risk."
        ),
    },
    {
        "order": 6,
        "title": "Legal Audit & Training",
        "icon_class": "fa-solid fa-clipboard-check",
        "description": (
            "We audit companies' legal structures and operations, providing practical "
            "advice on compliance and governance. We offer corporate training on "
            "employment law, credit management, commercial practices, and board "
            "governance. Our legal audits ensure businesses operate efficiently, "
            "minimize legal risks, and uphold best practices in all aspects of their "
            "corporate conduct."
        ),
    },
    {
        "order": 7,
        "title": "Probate Law & Estate Planning",
        "icon_class": "fa-solid fa-scroll",
        "description": (
            "We help individuals plan and manage their estates through wills, trusts, "
            "and succession strategies. Our services include probate applications, "
            "administration of estates, and dispute resolution. We ensure smooth "
            "transitions of assets and uphold clients' intentions while protecting "
            "beneficiaries' rights through legally sound and personalized estate "
            "planning solutions."
        ),
    },
    {
        "order": 8,
        "title": "Family Law",
        "icon_class": "fa-solid fa-people-roof",
        "description": (
            "We guide families through sensitive legal matters including divorce, "
            "child custody, adoption, guardianship, and maintenance. Our lawyers "
            "handle cases with empathy and professionalism, representing clients at "
            "all court levels. We focus on securing favorable outcomes while "
            "minimizing conflict, especially in matters affecting the welfare and "
            "stability of children."
        ),
    },
]


def seed_practice_areas(apps, schema_editor):
    PracticeArea = apps.get_model("core", "PracticeArea")
    for entry in PRACTICE_AREAS:
        PracticeArea.objects.update_or_create(
            title=entry["title"],
            defaults={
                "description": entry["description"],
                "icon_class": entry["icon_class"],
                "order": entry["order"],
                "is_active": True,
            },
        )


def unseed_practice_areas(apps, schema_editor):
    PracticeArea = apps.get_model("core", "PracticeArea")
    titles = [entry["title"] for entry in PRACTICE_AREAS]
    PracticeArea.objects.filter(title__in=titles).delete()


class Migration(migrations.Migration):

    dependencies = [
        # Make sure this matches whatever migration Django generates for you
        # in step 1 below (it will almost certainly be "0001_initial").
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_practice_areas, unseed_practice_areas),
    ]