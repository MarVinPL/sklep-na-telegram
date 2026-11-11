# Model danych — szkic 0.1

Każdy rekord należący do konkretnego sklepu musi być powiązany z `shop_id`. Dane globalne platformy (np. rejestr sklepów) są wyjątkiem i wymagają osobnych reguł dostępu.

## Główne encje

- **User** — tożsamość aplikacyjna powiązana z identyfikatorem Telegram.
- **Shop** — niezależny sklep, status, ustawienia i właściciel.
- **ShopMembership** — przypisanie użytkownika do sklepu i rola.
- **Category** — kategoria w obrębie sklepu.
- **Product** — produkt fizyczny, cyfrowy lub oferta usługi.
- **Inventory** — stan magazynowy dla produktów wymagających ewidencji.
- **Cart / CartItem** — koszyk przypisany do jednego sklepu.
- **Order / OrderItem** — zamówienie i niezmienny snapshot pozycji/cen.
- **Payment** — status i identyfikator transakcji u operatora; bez przechowywania danych kart.
- **Delivery** — sposób i status realizacji zamówienia.
- **ServiceReservation** — rezerwacja terminu usługi.
- **Coupon** — reguły promocji sklepu.
- **AuditEvent** — ślad istotnych działań administracyjnych.

## Wymagane ograniczenia

- Klucze obce i unikalności uwzględniające `shop_id`, gdzie dotyczy.
- Koszyk nie może zawierać produktów z różnych sklepów.
- Pozycje zamówienia przechowują cenę i nazwę z chwili zakupu.
- Status płatności zmienia wyłącznie zweryfikowany handler zdarzenia operatora lub uprawniona ścieżka administracyjna.
- Usunięcia i retencja danych muszą uwzględniać obowiązki prawne oraz politykę sklepu.

To dokument projektowy, nie gotowy schemat migracji SQL.
