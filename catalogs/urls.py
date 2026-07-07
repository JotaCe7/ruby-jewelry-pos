from rest_framework.routers import DefaultRouter

from .views import (
    ColorVariantViewSet,
    ExpenseCategoryViewSet,
    PaymentMethodViewSet,
    PresentationViewSet,
    ProductCategoryViewSet,
    ProductSubcategoryViewSet,
)

app_name = "catalogs"

router = DefaultRouter()
router.register("expense-categories", ExpenseCategoryViewSet, basename="expense-category")
router.register("payment-methods", PaymentMethodViewSet, basename="payment-method")
router.register("product-categories", ProductCategoryViewSet, basename="product-category")
router.register(
    "product-subcategories", ProductSubcategoryViewSet, basename="product-subcategory"
)
router.register("colors", ColorVariantViewSet, basename="color-variant")
router.register("presentations", PresentationViewSet, basename="presentation")

urlpatterns = router.urls
