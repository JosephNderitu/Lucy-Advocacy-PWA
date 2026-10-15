"""
Seed sample data for local testing.

Save as: core/management/commands/seed_test_data.py
(core/management/__init__.py and core/management/commands/__init__.py must exist, empty is fine)

Usage:
    python manage.py seed_test_data            # create or refresh the sample data
    python manage.py seed_test_data --clear    # remove only what this command created

Safe to run more than once: rows are matched by slug, name, title or IP and updated,
never duplicated. Nothing here uses images. Everything is obviously sample content,
so run --clear before going live.

How the sample rows are recognised:
    topics    by name, articles by slug, process steps by title
    reviews   by a reserved documentation IP (192.0.2.x), which no real visitor can have
"""
from datetime import timedelta

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import (
    PROCESS_CACHE_KEY,
    REVIEWS_CACHE_KEY,
    Article,
    ArticleTopic,
    ProcessSection,
    ProcessStep,
    Review,
)

# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------
TOPICS = [
    "Commercial Law",
    "Corporate Governance",
    "Employment Law",
    "Property and Conveyancing",
    "Litigation and Dispute Resolution",
    "Data Protection",
]

# ---------------------------------------------------------------------------
# Articles
#   published_days_ago > 0  -> live now
#   published_days_ago < 0  -> scheduled for the future (hidden until then)
#   published_days_ago None -> draft
#   excerpt "" -> the model builds one from the first paragraph
#   author ""  -> the model shows the firm name
# ---------------------------------------------------------------------------
ARTICLES = [
    {
        "slug": "check-before-signing-a-commercial-contract",
        "title": "What to check before signing a commercial contract",
        "headline": "Five things to check before you sign a commercial contract",
        "subheadline": "A short review now is far cheaper than a dispute later.",
        "excerpt": "Most contract disputes trace back to a clause nobody read closely. Here is what to look at first.",
        "author": "",
        "topics": ["Commercial Law"],
        "published_days_ago": 5,
        "body": [
            "Most commercial disputes begin with a clause that nobody read closely. The contract was signed in a hurry, the relationship was friendly, and the details seemed like a formality. Months later, when something goes wrong, those details decide who carries the loss.",
            "Start with the parties. Confirm the full legal name of each business, that it is properly registered, and that the person signing has authority to bind it. A contract signed by someone without authority can be difficult to enforce.",
            "Next, read the scope and payment terms together. The work or goods should be described clearly enough that a stranger could tell whether they were delivered. Payment dates, deposits, late payment consequences and who bears taxes and costs should all be written down.",
            "Then look at how the contract ends. Check the notice period, the reasons either side may terminate, and what happens to work already done. A clause that lets one party walk away freely while binding the other is worth negotiating.",
            "Finally, find the dispute resolution clause. It should say which law governs the contract and whether disagreements go first to negotiation or mediation before court. Taking an hour to review these five points with an advocate before signing is almost always cheaper than resolving a dispute afterwards.",
        ],
    },
    {
        "slug": "keeping-company-records-in-order",
        "title": "Keeping company records in order",
        "headline": "A short checklist for directors who want clean company records",
        "subheadline": "Good records protect the business and the people running it.",
        "excerpt": "",
        "author": "",
        "topics": ["Corporate Governance", "Commercial Law"],
        "published_days_ago": 12,
        "body": [
            "Directors are often surprised to learn how much of a company's legal health depends on paperwork. A business can trade well for years and still struggle to raise finance, sell shares or win a tender because its records are incomplete.",
            "Begin with the basics. Keep an up-to-date register of members and directors, a copy of the company's constitutional documents, and a clear record of who owns what. When ownership changes, update the records straight away rather than at year end.",
            "Hold board and shareholder meetings properly and minute them. Minutes do not need to be long, but they should record who attended, what was decided and why. They are often the first thing a bank, investor or court asks to see.",
            "Finally, diarise your filing obligations with the registrar and keep proof of every filing. A simple annual calendar, reviewed each quarter, prevents most problems. If you are unsure which requirements apply to your company, ask an advocate to run a short compliance check.",
        ],
    },
    {
        "slug": "choosing-the-right-employment-contract",
        "title": "Choosing the right employment contract",
        "headline": "Permanent, fixed term or casual: choosing the right employment contract",
        "subheadline": "The type of contract shapes your rights, your risks and how it can end.",
        "excerpt": "The wrong contract type is one of the most common sources of employment disputes. Here is how to choose well.",
        "author": "Legal Insights Desk",
        "topics": ["Employment Law"],
        "published_days_ago": 20,
        "body": [
            "Employers often treat the contract as a formality and the hiring decision as the real work. In practice, the type of contract you choose affects notice, benefits, how the relationship can end and what happens if there is a disagreement.",
            "A permanent contract suits roles that are ongoing and central to the business. It gives the employee security and gives the employer a stable team, but it also means any termination must follow a fair process and rest on a valid reason.",
            "A fixed term contract fits work with a defined end, such as a project or a cover role. It should state the start and end dates clearly. Repeatedly renewing short fixed term contracts for what is really permanent work can create problems for the employer.",
            "Casual and task based arrangements are meant for genuinely irregular work. Calling someone casual does not remove the employer's obligations if the person in fact works regular hours. Whatever you choose, put the terms in writing, keep them current and make sure the way you actually work matches what the document says.",
        ],
    },
    {
        "slug": "buying-land-due-diligence-checklist",
        "title": "Buying land: a due diligence checklist",
        "headline": "Before you pay a deposit on land, do these checks first",
        "subheadline": "Due diligence is the cheapest protection a buyer has.",
        "excerpt": "",
        "author": "",
        "topics": ["Property and Conveyancing"],
        "published_days_ago": 33,
        "body": [
            "Buying land is often the largest purchase a person makes, and mistakes are expensive to fix. Most of the problems buyers face could have been spotted in the first two weeks, before any money changed hands.",
            "Start by confirming that the seller is the registered owner and that the person you are dealing with is who they say they are. Compare the identity documents against the title and be cautious if the seller cannot meet in person or is represented by someone without clear written authority.",
            "Carry out an official search at the relevant land registry to see the current registered owner and whether the land is charged, restricted or otherwise encumbered. Visit the land itself and check that the boundaries, size and access match the paperwork.",
            "Confirm that rates and rent are paid up and that any consents the transaction needs have been obtained. Only then agree the sale terms, and have an advocate prepare or review the sale agreement. Paying a deposit first and checking later is the mistake that causes the most regret.",
        ],
    },
    {
        "slug": "mediation-or-court-business-disputes",
        "title": "Mediation or court for a business dispute",
        "headline": "Mediation or court: how to choose the right path for a business dispute",
        "subheadline": "The best outcome is not always the one that ends in a judgment.",
        "excerpt": "Court is sometimes necessary, but it is rarely the fastest or cheapest way to settle a commercial disagreement.",
        "author": "",
        "topics": ["Litigation and Dispute Resolution", "Commercial Law"],
        "published_days_ago": 47,
        "body": [
            "When a business relationship breaks down, the instinct is often to head straight for court. Litigation has its place, but it is slow, public and expensive, and a judgment does not always repair the commercial relationship or put money back in the bank.",
            "Kenyan law encourages alternative dispute resolution, and the Constitution itself promotes it. Negotiation, mediation and arbitration are all well established, and many commercial contracts require parties to try them before going to court.",
            "Mediation suits disputes where the parties still want to do business, or where a quick and private outcome matters. A neutral mediator helps both sides explore a settlement, but cannot impose one. If talks fail, nothing is lost and court remains available.",
            "Arbitration is closer to court. An arbitrator hears both sides and issues a binding decision, usually faster and more privately than a trial. It works well when the contract provides for it and the parties want a decision from someone with commercial or technical expertise.",
            "Court is the right choice when you need urgent orders, when the other side will not engage, or when a precedent or public ruling matters to you. Before choosing, weigh the amount in dispute, the evidence you hold, the cost and time involved, and whether you need to keep working with the other party.",
            "Whichever route you take, preparation matters. Collect the contract, correspondence, invoices and any records that show what was agreed and what actually happened. Decide in advance what outcome you would accept and what you would not, and who on your side has authority to settle. Parties who arrive organised tend to negotiate from strength, and they usually reach an agreement sooner.",
            "A sensible first step is a candid assessment of your position with an advocate. Often the strongest approach is to prepare as if you were going to court while keeping the door open to settlement, because a credible case makes every other option more likely to succeed.",
        ],
    },
    {
        # Draft: should never appear on the public site
        "slug": "data-protection-basics-for-small-businesses",
        "title": "Data protection basics for small businesses",
        "headline": "Data protection basics every small business should know",
        "subheadline": "If you keep customer details, these rules apply to you.",
        "excerpt": "",
        "author": "",
        "topics": ["Data Protection", "Corporate Governance"],
        "published_days_ago": None,
        "body": [
            "Almost every business collects personal data, from customer phone numbers to staff records. Kenya's Data Protection Act sets out how that information must be collected, stored and shared, and it applies to small businesses as well as large ones.",
            "Collect only what you need, tell people why you are collecting it and keep it secure. Decide how long you will hold each type of record and delete it when the reason for keeping it has gone.",
            "Check whether your business needs to register with the Office of the Data Protection Commissioner, and keep a short written policy that staff can actually follow.",
        ],
    },
    {
        # Scheduled: live only once the date arrives
        "slug": "debt-recovery-steps-before-filing-a-claim",
        "title": "Debt recovery: steps before filing a claim",
        "headline": "Owed money? Take these steps before you file a claim",
        "subheadline": "Good preparation makes recovery faster and cheaper.",
        "excerpt": "A well prepared demand often settles a debt without court. Here is how to build one.",
        "author": "",
        "topics": ["Litigation and Dispute Resolution", "Commercial Law"],
        "published_days_ago": -14,
        "body": [
            "Unpaid invoices can strain any business, and the pressure to act quickly is understandable. The strongest recovery efforts, however, start with careful preparation rather than a rushed court filing.",
            "Gather your records first: the signed contract or order, delivery proof, invoices, statements and any messages that acknowledge the debt. A clear paper trail is the backbone of any claim and often persuades the debtor to pay.",
            "Send a formal written demand that states the amount, how it was calculated and a reasonable deadline. Keep a copy and proof of delivery. Be mindful that time limits apply to bringing claims, so do not let a debt sit for years.",
            "If the debtor engages, consider a payment plan in writing. If they do not, an advocate can advise whether mediation, arbitration or a court claim is the most sensible next step for the amount involved.",
        ],
    },
]

# ---------------------------------------------------------------------------
# Our Process (singleton section + steps)
# ---------------------------------------------------------------------------
PROCESS_SECTION = {
    "is_published": True,
    "eyebrow": "Our Process",
    "heading": "How We Serve Our Clients",
    "intro": "A clear path from your first conversation to a final resolution, with a direct line to your advocate at every stage.",
}

PROCESS_STEPS = [
    {
        "title": "Initial Consultation",
        "description": "We listen to your matter in full before offering any view on strategy or cost.",
        "order": 1,
        "is_active": True,
    },
    {
        "title": "Tailored Strategy",
        "description": "A plan built for your specific goals, timeline and appetite for risk.",
        "order": 2,
        "is_active": True,
    },
    {
        "title": "Active Representation",
        "description": "Regular updates and direct access to the advocate handling your case.",
        "order": 3,
        "is_active": True,
    },
    {
        "title": "Resolution",
        "description": "A clear outcome, with follow-through on anything the resolution requires.",
        "order": 4,
        "is_active": True,
    },
    {
        # Inactive: should be hidden on the site, to test is_active
        "title": "Post-resolution Review",
        "description": "We check in after the matter closes to make sure everything agreed has been done.",
        "order": 5,
        "is_active": False,
    },
]

# ---------------------------------------------------------------------------
# Reviews. The ip values are from 192.0.2.0/24, reserved for documentation,
# so they double as a marker for --clear.
# ---------------------------------------------------------------------------
REVIEWS = [
    {"ip": "192.0.2.10", "name": "Jane Wanjiru", "rating": 5, "days_ago": 3,
     "message": "The firm explained every step of our company registration in plain language and kept to the timeline they promised. I always knew who was handling my file and could reach them directly."},
    {"ip": "192.0.2.11", "name": "Brian Otieno", "rating": 5, "days_ago": 9,
     "message": "Professional and responsive. They reviewed our supplier contract, flagged two clauses that would have cost us later, and negotiated better terms before we signed."},
    {"ip": "192.0.2.12", "name": "Amina Hassan", "rating": 4, "days_ago": 16,
     "message": "Clear advice on our land purchase and a thorough due diligence report. Documents took a little longer than I hoped, but communication throughout was excellent."},
    {"ip": "192.0.2.13", "name": "Peter Kamau", "rating": 5, "days_ago": 24,
     "message": "We came in with a dispute that had dragged on for months. The team gave us a realistic view of our options, and we settled on terms that worked for both sides."},
    {"ip": "192.0.2.14", "name": "Grace Achieng", "rating": 5, "days_ago": 31,
     "message": "Helpful from the first call. They made a stressful employment matter feel manageable and always returned my messages the same day."},
    {"ip": "192.0.2.15", "name": "David Mwangi", "rating": 4, "days_ago": 45,
     "message": "Knowledgeable advocates who care about the outcome. I liked being able to upload my documents and see their status online."},
    {"ip": "192.0.2.16", "name": "Faith Njeri", "rating": 5, "days_ago": 60,
     "message": "Honest counsel, even when the answer was not what I wanted to hear. I would recommend them to any business owner."},
    {"ip": "192.0.2.17", "name": "Samuel Kiprop", "rating": 3, "days_ago": 80,
     "message": "Good legal work overall. I would have liked more frequent updates in the first few weeks, though things improved after I raised it."},
]


class Command(BaseCommand):
    help = "Create (or with --clear, remove) sample topics, articles, process steps and reviews."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Remove only the rows this command created.")

    def handle(self, *args, **options):
        if options["clear"]:
            self._clear()
        else:
            with transaction.atomic():
                topics = self._seed_topics()
                self._seed_articles(topics)
                self._seed_process()
                self._seed_reviews()
            self.stdout.write(self.style.SUCCESS("Seeding complete."))
            self._summary()

        # Bulk updates skip the model signals, so clear the cached homepage blocks ourselves.
        cache.delete(REVIEWS_CACHE_KEY)
        cache.delete(PROCESS_CACHE_KEY)

    # -- seeding ------------------------------------------------------------
    def _seed_topics(self):
        topics = {}
        for name in TOPICS:
            topic, _ = ArticleTopic.objects.get_or_create(name=name)  # slug is generated by the model
            topics[name] = topic
        return topics

    def _seed_articles(self, topics):
        now = timezone.now()
        for data in ARTICLES:
            days = data["published_days_ago"]
            if days is None:
                status, published_at = "draft", None
            else:
                status, published_at = "published", now - timedelta(days=days)

            article, _ = Article.objects.update_or_create(
                slug=data["slug"],
                defaults={
                    "title": data["title"],
                    "headline": data["headline"],
                    "subheadline": data["subheadline"],
                    "excerpt": data["excerpt"],  # blank is filled in by Article.save()
                    "author_name": data["author"],
                    "body": "\n\n".join(data["body"]),
                    "status": status,
                    "published_at": published_at,
                },
            )
            article.topics.set([topics[name] for name in data["topics"]])

    def _seed_process(self):
        section, _ = ProcessSection.objects.update_or_create(pk=1, defaults=PROCESS_SECTION)
        for step in PROCESS_STEPS:
            ProcessStep.objects.update_or_create(
                section=section,
                title=step["title"],
                defaults={
                    "description": step["description"],
                    "order": step["order"],
                    "is_active": step["is_active"],
                },
            )

    def _seed_reviews(self):
        now = timezone.now()
        for r in REVIEWS:
            review, _ = Review.objects.update_or_create(
                ip_address=r["ip"],
                defaults={"name": r["name"], "message": r["message"], "rating": r["rating"]},
            )
            # created_at is auto_now_add, so spread the dates with a direct update.
            Review.objects.filter(pk=review.pk).update(created_at=now - timedelta(days=r["days_ago"]))

    # -- clearing -----------------------------------------------------------
    def _clear(self):
        slugs = [a["slug"] for a in ARTICLES]
        articles_deleted = Article.objects.filter(slug__in=slugs).delete()[0]
        # Only remove sample topics that no remaining article uses.
        topics_deleted = ArticleTopic.objects.filter(name__in=TOPICS, articles__isnull=True).delete()[0]
        steps_deleted = ProcessStep.objects.filter(title__in=[s["title"] for s in PROCESS_STEPS]).delete()[0]
        reviews_deleted = Review.objects.filter(ip_address__in=[r["ip"] for r in REVIEWS]).delete()[0]

        self.stdout.write(self.style.SUCCESS(
            f"Removed sample data: {articles_deleted} article rows, {topics_deleted} topic rows, "
            f"{steps_deleted} process steps, {reviews_deleted} reviews."
        ))
        self.stdout.write("The Process section itself was left in place. Edit or unpublish it in the admin.")

    def _summary(self):
        live = Article.objects.published().count()
        self.stdout.write(
            f"  Topics: {ArticleTopic.objects.count()}\n"
            f"  Articles: {Article.objects.count()} total, {live} live "
            f"({Article.objects.filter(status='draft').count()} draft, "
            f"{Article.objects.filter(status='published').count() - live} scheduled)\n"
            f"  Process steps: {ProcessStep.objects.count()} "
            f"({ProcessStep.objects.filter(is_active=True).count()} active)\n"
            f"  Reviews: {Review.objects.count()}"
        )