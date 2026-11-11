from telecourse.database import initialize, backup_database

if __name__ == '__main__':
    initialize()
    print('Backup criado:', backup_database())
