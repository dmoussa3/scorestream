import { useEffect, useRef } from 'react';

export function useNotifications() {
    const permissionRef = useRef(Notification.permission);

    useEffect(() => {
        if (permissionRef.current === 'default') {
            Notification.requestPermission().then(permission => {
                permissionRef.current = permission;
            });
        }
    }, []);

    const notify = (title, body, icon) => {
        if (permissionRef.current != 'granted') return;
        
        new Notification(title, {
            body,
            icon: icon || '/favicon.ico',
            badge: '/favicon.ico'
        })
    }

    return {notify};
}