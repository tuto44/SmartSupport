# Solicitud de Acceso a Global Protect

## 1. Acceso al portal
1. Acceda al portal de ServiceNow a través del siguiente enlace: [https://whirlpool.service-now.com/sp](https://whirlpool.service-now.com/sp)
2. Haga clic en la opción **“IT Service Catalog”**.
3. Seleccione **“Solicitudes de acceso”** y posteriormente elija **“Contractor VPN connectivity”**.

## 2. Llenado del formulario
1. Complete los campos requeridos en el formulario de solicitud.
2. Seleccione **“Vendor not listed”** e ingrese manualmente **“HWI”**. Luego, elija la opción **“Request VPN Connectivity option below”**.
3. En la sección *"Do you need VPN connectivity to an SAP instance"*, seleccione **“Sí”** y realice la búsqueda de **“mp0”**.
4. En el apartado *"Do you need VPN connectivity by VPN group membership"*, seleccione la opción **“No”**.
5. En la pregunta *"Do you need VPN connectivity to one or more specific internal network destinations?"*, marque la opción **“Sí”**.

## 3. Registro de Direcciones IP
Haga clic en **añadir** para registrar las siguientes direcciones IP con sus respectivas justificaciones:
- **SAP:** `10.3.68.27`
- **Windchill:** `10.16.20.191`

> **Nota de validación:** Asegúrese de que la configuración final refleje ambas direcciones IP ingresadas correctamente antes de proceder.

## 4. Finalizar solicitud
Finalmente, para procesar su solicitud, haga clic en el botón **“Ordene Ahora”**.