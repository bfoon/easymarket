from django.core.management.base import BaseCommand
from stores.models import Store
from finance.analytics import AdvancedFinancialAnalytics
from finance.reports import FinancialReportGenerator


class Command(BaseCommand):
    help = 'Generate advanced analytics report for all stores'

    def handle(self, *args, **options):
        for store in Store.objects.filter(status='active'):
            self.stdout.write(f'Generating analytics for {store.name}...')

            # Generate various analytics
            cohort_data = AdvancedFinancialAnalytics.get_cohort_analysis(store)
            seasonal_data = AdvancedFinancialAnalytics.get_seasonal_trends(store)
            margin_data = AdvancedFinancialAnalytics.get_profit_margin_analysis(store)

            # Generate monthly report
            from django.utils import timezone
            now = timezone.now()
            report_data = FinancialReportGenerator.generate_monthly_report(
                store, now.year, now.month
            )

            # Export to Excel
            filename = f"analytics_{store.name}_{now.year}_{now.month}.xlsx"
            FinancialReportGenerator.export_to_excel(report_data, filename)

            self.stdout.write(
                self.style.SUCCESS(f'✓ Generated analytics report: {filename}')
            )

        self.stdout.write(
            self.style.SUCCESS('All analytics reports generated successfully!')
        )